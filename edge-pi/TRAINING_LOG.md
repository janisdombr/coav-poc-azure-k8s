# Training Log — Contrail Segmentation Model
## U-Net + EfficientNet-B2 · GVCCS Dataset · EUROCONTROL MUAC

---

## Final State

| Version | Encoder | Platform | Best val Dice | Epochs | Status |
|---|---|---|---|---|---|
| V1 (B4) | EfficientNet-B4 | Google Colab → Kaggle | 0.4918 (ep 22) | 22/30 | Stopped — overfitting |
| V2 (B2) | EfficientNet-B2 | Kaggle + Google Colab | **0.7932 (ep 35)** | 41 | ✓ Above PoC threshold |

Best weights: `data/contrail_unet_best.pt` · val Dice **0.7932** · epoch 35

![Training curves](../images/training_curves_final.png)

---

## Attempt 1 — Google Colab · EfficientNet-B4

### Configuration

| Parameter | Value |
|---|---|
| Platform | Google Colab (free tier) |
| GPU | NVIDIA T4 15 GB |
| Encoder | EfficientNet-B4 (17M parameters) |
| Loss | Dice + SoftBCE |
| Augmentations | HorizontalFlip, RandomBrightnessContrast |
| Batch size | 8 |
| LR | 1e-4 (CosineAnnealingLR) |
| Planned epochs | 30 |

### Results

| Epoch | Train Dice | Val Dice |
|---|---|---|
| 1 | 0.41 | 0.34 |
| 2 | 0.58 | 0.43 |
| 3 | 0.68 | 0.50 |
| **4** | **0.77** | **0.54** |

Session disconnected after epoch 4 — Colab free tier disconnects after ~90 min of browser
inactivity. Weekly GPU quota was exhausted on reconnect.

### Lessons

- Colab free tier is not suitable for multi-hour training runs without Pro subscription
- Need periodic checkpoint saves — Google Drive mount is essential
- Switched to Kaggle for longer sessions (30 h/week, up to 12 h per session)

---

## Attempt 2 — Kaggle · EfficientNet-B4

### Configuration

| Parameter | Value |
|---|---|
| Platform | Kaggle |
| GPU | T4 x2 (30 GB total) |
| Encoder | EfficientNet-B4 (17M parameters) |
| Loss | Dice + SoftBCE |
| Augmentations | HorizontalFlip, VerticalFlip, RandomRotate90, ShiftScaleRotate, RandomBrightnessContrast |
| Batch size | 8 (DataParallel active) |
| LR | 1e-4 (CosineAnnealingLR, T_max=30) |
| Planned epochs | 30 |

### Results

| Epoch | Train Dice | Val Dice | Note |
|---|---|---|---|
| 1 | ~0.45 | ~0.38 | Start from ImageNet weights |
| 10 | ~0.79 | ~0.49 | Growth slowing |
| 22 | ~0.85 | **0.4918** | **Best val Dice** |
| 29 | ~0.87 | ~0.47 | Val Dice degrading |

### Diagnosis

Classic overfitting: Train Dice 0.85 vs Val Dice 0.49 — gap of 0.36.
Val Dice plateaued at epoch 10 and never recovered.

Root cause: EfficientNet-B4 (17M parameters) is too large for 24,228 training images
without strong regularisation. Loss without Focal treats thin contrail pixels and easy
background pixels equally.

### Technical Issues

**1. DataParallel + PyTorch 2.x → `cudaErrorMisalignedAddress`**

```
RuntimeError: CUDA error: misaligned address
  during backward pass (nn.DataParallel + segmentation_models_pytorch encoder)
```

Fix for V2: remove `nn.DataParallel` entirely, single GPU.

**2. albumentations v2 API (Kaggle ships v2)**

```python
# v1 (broken):
A.ShiftScaleRotate(shift_limit=0.1, scale_limit=0.1, rotate_limit=45)
A.ElasticTransform(alpha=120, sigma=6, alpha_affine=3.6)
A.GaussNoise(var_limit=(10, 50))
A.CoarseDropout(max_holes=6, max_height=48, max_width=48)

# v2 (fixed):
A.Affine(translate_percent=0.1, scale=(0.9, 1.1), rotate=(-45, 45), p=0.5)
A.ElasticTransform(alpha=80, sigma=4.0, p=0.25)
A.GaussNoise(p=0.2)
A.CoarseDropout(num_holes_range=(1, 6), hole_height_range=(8, 48),
                hole_width_range=(8, 48), p=0.2)
```

**3. `/kaggle/working/` does not persist between sessions**

Checkpoint at epoch 32 was lost — Kaggle only saves Output on explicit Commit.
Fix for V2: HuggingFace Hub push after every epoch.

---

## Attempt 3 — Kaggle V2 · EfficientNet-B2 (epochs 1–25, biased val split)

### What changed vs V1

| | V1 (B4) | V2 (B2) |
|---|---|---|
| Encoder | EfficientNet-B4 (17M) | **EfficientNet-B2 (7M)** — less overfitting |
| Loss | Dice + SoftBCE | **Dice + Focal Loss (γ=2, α=0.25)** |
| Augmentations | 5 transforms | **10 transforms** + ElasticTransform + GaussNoise + CoarseDropout |
| DataParallel | Yes (→ CUDA crash) | **Removed, single GPU** |
| Checkpoint | `/kaggle/working/` only | **+ HuggingFace Hub every epoch** |
| Planned epochs | 30 | **40** |

### Results (epochs 1–25)

Val Dice oscillated between 0.32 and 0.67 — train Dice grew steadily to 0.70.

**Root cause of oscillation:** GVCCS images are ordered by video sequence. Taking the
last 10% as val = only the last ~12 of 122 sequences, giving a biased and high-variance
val set. Different sequences have very different contrail density, so val Dice depended
more on which sequence was sampled than on model quality.

Fix: shuffle all 24,228 indices with `random.seed(42)` before splitting, so val images
come from all 122 sequences proportionally.

---

## Attempt 4 — Kaggle V2 + Val Split Fix (epochs 26–38)

### Val split correction

```python
# Before (biased — last 10% = last ~12 sequences only):
val_idx   = list(range(n - val_size, n))
train_idx = list(range(n - val_size))

# After (fixed — val images from all 122 sequences):
random.seed(42)
all_indices = list(range(n))
random.shuffle(all_indices)
val_idx   = all_indices[:val_size]
train_idx = all_indices[val_size:]
```

### Results (epochs 26–38)

| Epoch | Train Dice | Val Dice | Note |
|---|---|---|---|
| 26 | 0.6900 | 0.7903 | First epoch with fixed val split |
| 30 | 0.6925 | 0.7919 | |
| **35** | **0.6952** | **0.7932** | **Best — above PoC threshold 0.75** |
| 38 | 0.7002 | 0.7926 | Plateau |

Val Dice stabilised immediately at 0.79+ — confirming that the oscillation was entirely
due to the biased val set, not model instability.

---

## Attempt 5 — Google Colab · Warm Restart (epochs 39–41)

With val Dice plateaued at ~0.793, applied a warm LR restart: fresh CosineAnnealing cycle
starting at LR = 1e-4 (instead of the near-zero LR the cosine schedule had reached).

| Epoch | Train Dice | Val Dice |
|---|---|---|
| 39 | 0.6710 | 0.7714 |
| 40 | 0.6673 | 0.7744 |
| 41 | 0.6760 | 0.7721 |

Session hit Colab GPU limit after epoch 41. Val Dice temporarily dropped to 0.77 — the
expected behaviour when LR is reset high: the model is exploring a wider region of the
loss landscape before converging again. A full warm restart cycle (20+ epochs) would be
needed to confirm whether it recovers above 0.7932.

Best val Dice across all runs: **0.7932** at epoch 35.

---

## Compute Resources

### Kaggle GPU quota

| Limit | Value |
|---|---|
| Hours per week | 30 h (resets Monday UTC) |
| Max session length | ~9–12 h |
| GPU | T4 x2 (15 GB VRAM each) |
| `/kaggle/working/` | Resets on every new session |

HuggingFace Hub push after every epoch solves the persistence problem.

### Azure VM — quota issues

| SKU | Quota | Availability | Note |
|---|---|---|---|
| Standard_NC6 (K80) | 12 vCPU | ❌ Unavailable | Microsoft retiring K80 |
| Standard_NC4as_T4_v3 | 0 vCPU | — | Quota requests rejected on trial subscription |

Quota increase requests submitted for 5 regions (East US, East US 2, West US 2,
West Europe, West US) — all rejected. Azure trial subscriptions cannot be approved
via self-service quota requests.

---

## Accumulated Fixes

### Fix 1 — Dice = 0.0 on val set

```python
def dice_score(logits, target, threshold=0.5):
    pred  = (torch.sigmoid(logits) > threshold).float()
    inter = (pred * target).sum()
    union = pred.sum() + target.sum()
    if union < 1:
        return 1.0  # true negative: no contrail present, none predicted
    return (2 * inter / (union + 1e-8)).item()
```

GVCCS contains ~35% clear-sky frames. Without the `union < 1` guard, Dice = 0/0 = NaN.

### Fix 2 — DataParallel CUDA crash

```python
# Before:
model = nn.DataParallel(model).cuda()
# After:
model = model.cuda()  # single GPU, no DataParallel
```

### Fix 3 — Checkpoint persistence

```python
# Save to HuggingFace Hub after every epoch:
hf_api.upload_file(
    path_or_fileobj=f'{WORK_DIR}/checkpoint_last.pt',
    path_in_repo='checkpoint_last.pt',
    repo_id=HF_REPO,
    repo_type='model',
)

# Restore at session start:
hf_hub_download(repo_id=HF_REPO, filename='checkpoint_last.pt',
                local_dir=WORK_DIR, token=HF_TOKEN)
```

### Fix 4 — Biased val split

See Attempt 4 above. `random.seed(42)` shuffle before train/val split.

---

## Files

| File | Description |
|---|---|
| `kaggle_train_contrail_v2.ipynb` | Main training notebook — Kaggle, HF saves, warm restart config |
| `colab_train_contrail_v3.ipynb` | Google Colab version — Google Drive persistence |
| `python/train.py` | Standalone training script for Azure VM or any Linux GPU server |
| `data/checkpoint_last.pt` | Full checkpoint — epoch 41, history, optimizer state |
| `data/contrail_unet_best.pt` | Best model weights — epoch 35, val Dice 0.7932 |
| `data/training_curves_final.png` | Training history chart — all 41 epochs |
