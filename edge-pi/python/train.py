#!/usr/bin/env python3
"""
Contrail segmentation training — U-Net + EfficientNet-B2
GVCCS dataset · Zenodo 15743988 · CC BY 4.0 · EUROCONTROL MUAC

Usage:
    HF_TOKEN=hf_xxx HF_REPO=username/coav-contrail-checkpoints python train.py
    HF_TOKEN=hf_xxx HF_REPO=username/coav-contrail-checkpoints python train.py --epochs 25
"""

import os, sys, json, time, signal, argparse, logging
import cv2, numpy as np, torch
import segmentation_models_pytorch as smp
import albumentations as A
from albumentations.pytorch import ToTensorV2
from pathlib import Path
from torch.utils.data import Dataset, DataLoader
from huggingface_hub import HfApi, hf_hub_download

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(message)s',
    datefmt='%H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ── Args ──────────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--encoder',    default='efficientnet-b2')
    p.add_argument('--epochs',     type=int, default=40)
    p.add_argument('--batch',      type=int, default=8)
    p.add_argument('--img-size',   type=int, default=512)
    p.add_argument('--lr',         type=float, default=1e-4)
    p.add_argument('--push-every', type=int, default=1,
                   help='Push checkpoint to HF Hub every N epochs')
    p.add_argument('--work-dir',   default='/tmp/coav-train')
    p.add_argument('--data-dir',   default=None)
    return p.parse_args()

ARGS     = parse_args()
HF_TOKEN = os.environ.get('HF_TOKEN', '')
HF_REPO  = os.environ.get('HF_REPO', '')
WORK_DIR = ARGS.work_dir
DATA_DIR = ARGS.data_dir or f'{WORK_DIR}/GVCCS/train'
SAVE_DIR = WORK_DIR
os.makedirs(WORK_DIR, exist_ok=True)

if not HF_TOKEN:
    log.warning('HF_TOKEN not set — checkpoints will NOT be pushed to HuggingFace')
if not HF_REPO:
    log.warning('HF_REPO not set  — checkpoints will NOT be pushed to HuggingFace')

# ── GPU ───────────────────────────────────────────────────────────────────────
N_GPU = torch.cuda.device_count()
log.info(f'PyTorch {torch.__version__}  |  GPUs: {N_GPU}')
for i in range(N_GPU):
    p = torch.cuda.get_device_properties(i)
    log.info(f'  GPU {i}: {p.name}  {p.total_memory/1e9:.1f} GB')
if N_GPU == 0:
    raise RuntimeError('No GPU found. Check nvidia-smi.')
DEVICE = torch.device('cuda:0')

# ── HuggingFace ───────────────────────────────────────────────────────────────
hf_api = None
if HF_TOKEN and HF_REPO:
    hf_api = HfApi(token=HF_TOKEN)
    try:
        hf_api.create_repo(repo_id=HF_REPO, repo_type='model', private=True, exist_ok=True)
        log.info(f'HF repo ready → https://huggingface.co/{HF_REPO}')
    except Exception as e:
        log.warning(f'HF repo create failed: {e}')

def push_to_hf(is_best=False):
    if not hf_api:
        return
    files = ['checkpoint_last.pt']
    if is_best:
        files.append('contrail_unet_best.pt')
    for fname in files:
        path = f'{SAVE_DIR}/{fname}'
        if os.path.exists(path):
            try:
                hf_api.upload_file(
                    path_or_fileobj=path,
                    path_in_repo=fname,
                    repo_id=HF_REPO,
                    repo_type='model',
                )
                log.info(f'[HF] Pushed {fname}')
            except Exception as e:
                log.warning(f'[HF] Push {fname} failed: {e}')

def restore_from_hf():
    if not hf_api:
        return None
    try:
        local = hf_hub_download(
            repo_id=HF_REPO, filename='checkpoint_last.pt',
            repo_type='model', token=HF_TOKEN,
            local_dir=SAVE_DIR,
        )
        log.info('[HF] Checkpoint restored from HuggingFace')
        return local
    except Exception:
        log.info('[HF] No checkpoint on HF — fresh start')
        return None

# ── Data download ─────────────────────────────────────────────────────────────
def download_gvccs():
    if os.path.exists(DATA_DIR):
        log.info('GVCCS already present')
        return
    log.info('Downloading GVCCS from Zenodo (~2.1 GB)...')
    import urllib.request, zipfile
    zip_path = f'{WORK_DIR}/GVCCS.zip'
    url = 'https://zenodo.org/records/15743988/files/GVCCS.zip?download=1'

    def progress(block, block_size, total):
        done = block * block_size
        if total > 0 and done % (200 * 1024 * 1024) < block_size:
            log.info(f'  {done/1e9:.2f} / {total/1e9:.2f} GB downloaded')

    urllib.request.urlretrieve(url, zip_path, reporthook=progress)
    log.info('Extracting...')
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(WORK_DIR)
    os.remove(zip_path)
    log.info('GVCCS ready')

# ── Dataset ───────────────────────────────────────────────────────────────────
class GVCCSDataset(Dataset):
    def __init__(self, data_dir, transform=None, indices=None):
        self.data_dir  = Path(data_dir)
        self.transform = transform
        with open(self.data_dir / 'annotations.json') as f:
            coco = json.load(f)
        self.ann_by_img = {}
        for ann in coco['annotations']:
            self.ann_by_img.setdefault(ann['image_id'], []).append(ann)
        imgs = coco['images']
        self.images = [imgs[i] for i in indices] if indices is not None else imgs

    def __len__(self): return len(self.images)

    def __getitem__(self, idx):
        meta  = self.images[idx]
        image = cv2.cvtColor(
            cv2.imread(str(self.data_dir / 'images' / meta['file_name'])),
            cv2.COLOR_BGR2RGB)
        h, w  = meta.get('height', 1024), meta.get('width', 1024)
        mask  = np.zeros((h, w), dtype=np.uint8)
        for ann in self.ann_by_img.get(meta['id'], []):
            for seg in ann.get('segmentation', []):
                cv2.fillPoly(mask, [np.array(seg, dtype=np.int32).reshape(-1, 2)], 1)
        if self.transform:
            r = self.transform(image=image, mask=mask)
            return r['image'], r['mask'].unsqueeze(0).float()
        return image, mask

# ── Augmentations ─────────────────────────────────────────────────────────────
MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]
S = ARGS.img_size

train_tf = A.Compose([
    A.Resize(S, S),
    A.HorizontalFlip(p=0.5),
    A.VerticalFlip(p=0.2),
    A.RandomRotate90(p=0.5),
    A.Affine(translate_percent=0.1, scale=(0.9, 1.1), rotate=(-45, 45), p=0.5),
    A.ElasticTransform(alpha=80, sigma=4.0, p=0.25),
    A.RandomBrightnessContrast(brightness_limit=0.25, contrast_limit=0.25, p=0.5),
    A.GaussianBlur(blur_limit=3, p=0.15),
    A.GaussNoise(p=0.2),
    A.CoarseDropout(num_holes_range=(1, 6), hole_height_range=(8, 48),
                    hole_width_range=(8, 48), p=0.2),
    A.Normalize(mean=MEAN, std=STD),
    ToTensorV2(),
])
val_tf = A.Compose([
    A.Resize(S, S),
    A.Normalize(mean=MEAN, std=STD),
    ToTensorV2(),
])

# ── Loss ──────────────────────────────────────────────────────────────────────
dice_loss  = smp.losses.DiceLoss(mode='binary')
focal_loss = smp.losses.FocalLoss(mode='binary', gamma=2.0, alpha=0.25)
loss_fn    = lambda p, t: dice_loss(p, t) + focal_loss(p, t)

def dice_score(logits, target, threshold=0.5):
    pred  = (torch.sigmoid(logits) > threshold).float()
    inter = (pred * target).sum()
    union = pred.sum() + target.sum()
    if union < 1:
        return 1.0
    return (2 * inter / (union + 1e-8)).item()

# ── Checkpoint I/O ────────────────────────────────────────────────────────────
def save_checkpoint(model, optimizer, scheduler, epoch, best_dice, history, is_best):
    ckpt = {
        'epoch':           epoch,
        'encoder':         ARGS.encoder,
        'model_state':     model.state_dict(),
        'optimizer_state': optimizer.state_dict(),
        'scheduler_state': scheduler.state_dict(),
        'best_dice':       best_dice,
        'history':         history,
    }
    torch.save(ckpt, f'{SAVE_DIR}/checkpoint_last.pt')
    if is_best:
        torch.save(model.state_dict(), f'{SAVE_DIR}/contrail_unet_best.pt')
        log.info(f'  New best → contrail_unet_best.pt  (dice={best_dice:.4f})')

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    download_gvccs()

    import random
    with open(f'{DATA_DIR}/annotations.json') as f:
        n_total = len(json.load(f)['images'])
    # GVCCS images are ordered by video sequence — last 10% = only last ~12 sequences.
    # Shuffle with fixed seed so val images come from ALL 122 sequences uniformly.
    random.seed(42)
    all_idx   = list(range(n_total))
    random.shuffle(all_idx)
    val_size  = int(n_total * 0.1)
    val_idx   = all_idx[:val_size]
    train_idx = all_idx[val_size:]
    log.info(f'Train: {len(train_idx)}  Val: {len(val_idx)}  (shuffled, seed=42)')

    train_loader = DataLoader(
        GVCCSDataset(DATA_DIR, train_tf, train_idx),
        batch_size=ARGS.batch, shuffle=True, num_workers=4, pin_memory=True)
    val_loader = DataLoader(
        GVCCSDataset(DATA_DIR, val_tf, val_idx),
        batch_size=ARGS.batch, shuffle=False, num_workers=4, pin_memory=True)

    model = smp.Unet(
        encoder_name=ARGS.encoder, encoder_weights='imagenet',
        in_channels=3, classes=1, activation=None,
    ).to(DEVICE)
    log.info(f'Model: {ARGS.encoder}  '
             f'params={sum(p.numel() for p in model.parameters())/1e6:.1f}M')

    start_epoch = 1
    best_dice   = 0.0
    history     = []

    ckpt_path = f'{SAVE_DIR}/checkpoint_last.pt'
    if not os.path.exists(ckpt_path):
        ckpt_path = restore_from_hf()

    if ckpt_path and os.path.exists(str(ckpt_path)):
        ckpt = torch.load(ckpt_path, map_location='cpu')
        if isinstance(ckpt, dict) and 'model_state' in ckpt:
            model.load_state_dict(ckpt['model_state'])
            start_epoch = ckpt.get('epoch', 0) + 1
            best_dice   = ckpt.get('best_dice', 0.0)
            history     = ckpt.get('history', [])
            log.info(f'Resumed from epoch {start_epoch - 1}, best_dice={best_dice:.4f}')
    else:
        log.info('Fresh start from ImageNet weights')

    if start_epoch > ARGS.epochs:
        log.info(f'Already completed {ARGS.epochs} epochs. Nothing to do.')
        return

    optimizer = torch.optim.AdamW(model.parameters(), lr=ARGS.lr, weight_decay=2e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=ARGS.epochs, eta_min=1e-6)
    for _ in range(start_epoch - 1):
        scheduler.step()
    log.info(f'LR at epoch {start_epoch}: {scheduler.get_last_lr()[0]:.2e}')

    interrupted = False
    def _handler(sig, frame):
        nonlocal interrupted
        log.info('Signal received — will stop after this epoch and push to HF')
        interrupted = True
    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT,  _handler)

    log.info(f'--- Training epochs {start_epoch}–{ARGS.epochs} ---')

    for epoch in range(start_epoch, ARGS.epochs + 1):
        t0 = time.time()

        model.train()
        tr_loss = tr_dice = 0.0
        for i, (images, masks) in enumerate(train_loader):
            images, masks = images.to(DEVICE), masks.to(DEVICE)
            optimizer.zero_grad()
            loss = loss_fn(model(images), masks)
            loss.backward()
            optimizer.step()
            with torch.no_grad():
                tr_loss += loss.item()
                tr_dice += dice_score(model(images), masks)
            if (i + 1) % 200 == 0:
                log.info(f'  [{epoch:02d}] batch {i+1}/{len(train_loader)}'
                         f'  loss={tr_loss/(i+1):.4f}  dice={tr_dice/(i+1):.4f}')

        model.eval()
        vl_loss = vl_dice = 0.0
        with torch.no_grad():
            for images, masks in val_loader:
                images, masks = images.to(DEVICE), masks.to(DEVICE)
                logits = model(images)
                vl_loss += loss_fn(logits, masks).item()
                vl_dice += dice_score(logits, masks)

        scheduler.step()
        nb, nvb = len(train_loader), len(val_loader)
        ep_dice = vl_dice / nvb
        is_best = ep_dice > best_dice
        if is_best:
            best_dice = ep_dice

        history.append(dict(epoch=epoch,
                            tr_loss=tr_loss/nb, tr_dice=tr_dice/nb,
                            vl_loss=vl_loss/nvb, vl_dice=ep_dice))

        save_checkpoint(model, optimizer, scheduler, epoch, best_dice, history, is_best)

        log.info(f'Ep {epoch:02d}/{ARGS.epochs}  '
                 f'tr loss={tr_loss/nb:.4f} dice={tr_dice/nb:.4f}  '
                 f'val loss={vl_loss/nvb:.4f} dice={ep_dice:.4f}  '
                 f'{time.time()-t0:.0f}s{"  ← BEST" if is_best else ""}')

        if epoch % ARGS.push_every == 0:
            push_to_hf(is_best=is_best)

        if interrupted:
            log.info('Stopped — checkpoint saved and pushed to HF')
            break

    log.info(f'=== Done. Best val Dice: {best_dice:.4f} ===')
    if HF_REPO:
        log.info(f'Model: https://huggingface.co/{HF_REPO}')

if __name__ == '__main__':
    main()
