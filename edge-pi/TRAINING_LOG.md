# Training Log — Contrail Segmentation Model
## U-Net + EfficientNet-B2 · GVCCS Dataset · EUROCONTROL MUAC

---

## Final State

| Run | Encoder | Epochs | Best val Dice | Method | Status |
|---|---|---|---|---|---|
| V1 (B4) | EfficientNet-B4 | 22 | 0.4918 (ep 22) | Colab → Kaggle | Stopped — overfitting |
| V2 (B2) | EfficientNet-B2 | 38 | 0.7932 (ep 35) | Kaggle, val split fix | ✓ Above PoC 0.75 |
| WR-1 | EfficientNet-B2 | 60 | 0.8085 (ep 59) | Warm Restart (LR reset 1e-4) | ✓ +0.015 vs baseline |
| **WR-2** | EfficientNet-B2 | **90** | **0.8394 (ep 88, global)** | **Warm Restart + calibration** | **✓ Current best (calibrated)** |
| WR-3 + SWA | EfficientNet-B2 | 120 | 0.8343 (ep 116, per-batch EMA) · SWA avg 0.8249 (ep118-120) | Warm Restart + weight averaging | Plateau — SWA −0.0094 vs EMA, kept EMA |

**Warm Restart (WR):** LR scheduler resets to `1e-4` (start of a new cosine cycle) instead of staying at `eta_min`. The model escapes the local minimum it converged to and finds a wider, flatter one.

**SWA (Stochastic Weight Averaging):** at the end of each cosine cycle (when LR is near zero) the model orbits its minimum in small steps. Averaging weights from those final epochs lands at the center of a flat valley — better generalisation with no extra training.

Best weights (current `data/contrail_unet_best.pt`): epoch 116, per-batch EMA val Dice **0.8343**.
This is the best single-checkpoint snapshot across the full 120-epoch run (WR-1 + WR-2 + WR-3 + SWA);
it supersedes the WR-2 epoch-88 weights that were previously calibrated to a global Dice of 0.8394.
**The global Dice for this new epoch-116 checkpoint has not been recalibrated** (threshold sweep
over the full val set is a multi-minute GPU pass — not re-run for this update). Until it is,
**0.8394 (WR-2, epoch 88, t=0.50) remains the last confirmed calibrated reference number** for
reporting purposes; the honest summary is that the model has **plateaued around 0.83–0.84 Dice**
since WR-2, and WR-3 + SWA did not produce a clear further improvement. See Attempt 8 below.

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

| Epoch | Train Dice | Val Dice | Train Loss | Val Loss |
|---|---|---|---|---|
| 39 | 0.6710 | 0.7714 | 0.3646 | 0.2597 |
| 40 | 0.6673 | 0.7744 | 0.3686 | 0.2551 |
| 41 | 0.6760 | 0.7721 | 0.3591 | 0.2601 |

Session hit Colab GPU limit after epoch 41. Val Dice temporarily dropped to 0.77 — the
expected behaviour when LR is reset high: the model is exploring a wider region of the
loss landscape before converging again.

---

## Attempt 6 — Google Colab · Warm Restart Recovery (epochs 42–60)

Continued the warm restart cycle. Val Dice steadily recovered and then surpassed the
previous best of 0.7932, confirming that the warm restart successfully escaped the
local minimum the model was stuck in at epoch 38.

| Epoch | Train Dice | Val Dice | Train Loss | Val Loss | Note |
|---|---|---|---|---|---|
| 42 | 0.6789 | 0.7748 | 0.3561 | 0.2546 | Recovery begins |
| 43 | 0.6769 | 0.7789 | 0.3581 | 0.2502 | |
| 44 | 0.6846 | 0.7806 | 0.3496 | 0.2489 | |
| 45 | 0.6862 | 0.7811 | 0.3479 | 0.2476 | |
| 46 | 0.6862 | 0.7848 | 0.3477 | 0.2437 | |
| 47 | 0.6971 | 0.7887 | 0.3360 | 0.2391 | |
| 48 | 0.6953 | 0.7893 | 0.3377 | 0.2383 | |
| 49 | 0.7005 | 0.7894 | 0.3321 | 0.2383 | |
| 50 | 0.7049 | 0.7909 | 0.3272 | 0.2366 | |
| 51 | 0.7114 | 0.7942 | 0.3201 | 0.2324 | Surpasses previous best |
| 52 | 0.7144 | 0.7967 | 0.3167 | 0.2295 | |
| 53 | 0.7154 | 0.7975 | 0.3157 | 0.2288 | |
| 54 | 0.7199 | 0.8013 | 0.3106 | 0.2245 | |
| 55 | 0.7232 | 0.8024 | 0.3071 | 0.2236 | |
| 56 | 0.7260 | 0.8053 | 0.3040 | 0.2207 | |
| 57 | 0.7287 | 0.8050 | 0.3010 | 0.2205 | |
| 58 | 0.7270 | 0.8060 | 0.3027 | 0.2194 | |
| **59** | **0.7323** | **0.8085** | **0.2970** | **0.2166** | **Best** |
| 60 | 0.7379 | 0.8084 | 0.2911 | 0.2169 | Plateau — stopped |

Val Dice crossed 0.80 at epoch 54 and peaked at **0.8085** (epoch 59).
Train Dice is 0.7323 vs Val Dice 0.8085 — the gap has nearly closed compared to V1's
0.36 gap, confirming that the architecture change (B4→B2) and augmentation improvements
are preventing overfitting.

---

## Attempt 7 — Kaggle · WR-2 (epochs 61–90)

### What is Warm Restart

After a cosine cycle the LR reaches `eta_min=1e-6` — the model stops exploring.
A **Warm Restart** resets LR back to `1e-4` (start of a new cosine cycle).
The high LR pushes the model out of the local minimum it converged to,
and the subsequent decay finds a better (wider, flatter) minimum.

```
Cosine schedule:    LR
                1e-4 ─╮              ╭─╮              ╭─╮
                      │              │ │              │ │
                      ╰──────────────╯ ╰──────────────╯ ╰──→ epoch
                      ep38         ep60            ep90
                       ↑ WR-1           ↑ WR-2           ↑ WR-3
```

### Results (epochs 61–90)

| Epoch | Train Dice | Val Dice | LR | Note |
|---|---|---|---|---|
| 61 | 0.7144 | 0.7938 | 9.97e-05 | WR-2 start — expected dip |
| 65 | 0.7183 | 0.8018 | 9.34e-05 | Recovery |
| 70 | 0.7313 | 0.8013 | 7.52e-05 | |
| 75 | 0.7433 | 0.8093 | 5.05e-05 | Surpasses WR-1 best |
| 80 | 0.7586 | 0.8180 | 2.58e-05 | |
| 85 | 0.7592 | 0.8225 | 7.63e-06 | |
| **88** | **0.7647** | **0.8232** | **2.08e-06** | **Best (per-batch avg)** |
| 89 | 0.7645 | 0.8225 | 1.27e-06 | |
| 90 | 0.7616 | 0.8227 | 1.00e-06 | Cycle end — LR at minimum |

### Threshold calibration (post-training)

After loading best weights, global Dice was computed across entire val set:

| Threshold | Global Dice |
|---|---|
| 0.40 | 0.8371 |
| **0.50** | **0.8394** |
| 0.55 | 0.8381 |
| 0.60 | 0.8312 |

**Global Dice (0.8394) ≠ per-batch average (0.8232).**  
The training loop computes Dice per-batch and averages — this is noisy on small batches
containing mostly clear-sky frames (where Dice = 1.0 by definition, inflating the average).
Global Dice computes one numerator and one denominator across all val images — more stable
and the correct metric for reporting.

### TTA analysis

4-orientation TTA (H-flip + V-flip + HV-flip) **hurt** the result: −0.0147.

Root causes:
1. **Wrong threshold post-averaging.** Averaging 4 probability maps squishes confident
   pixels toward 0.5. Pixels at p=0.55 drop below t=0.50 → contrail pixels missed.
2. **V-flip adds out-of-distribution noise.** Sky is always at top in ground cameras.
   V-flip trained at p=0.20 only — the model is systematically less confident on
   vertically-flipped images, and averaging these noisy predictions with the correct one
   drags the result down.

**Fix:** H-flip only TTA (2 orientations) + separate threshold calibration for TTA probs.

Best val Dice across all runs: **0.8394** (global Dice, epoch 88, t=0.50).

---

## Attempt 8 — Kaggle/Colab · WR-3 + SWA (epochs 91–120)

### What is SWA

**Stochastic Weight Averaging (SWA)** maintains a running average of the model's weights
during the final, low-LR portion of a cosine cycle, instead of just keeping the single
snapshot with the best per-batch Dice. Near the end of a cycle the optimiser orbits a
minimum in small steps; averaging several nearby snapshots lands closer to the centre of
that flat region, which typically generalises slightly better than any one snapshot
("no free extra training" — same weights, different combination).

```python
def update_swa(model):
    # Welford-style online average of model.parameters()
    global swa_model, swa_n
    swa_n += 1
    if swa_model is None:
        swa_model = copy.deepcopy(model)
        return
    for p_avg, p_new in zip(swa_model.parameters(), model.parameters()):
        p_avg.data.mul_(1 - 1 / swa_n).add_(p_new.data / swa_n)
```

Planned: average the final 10 epochs of the WR-3 cycle (epoch 111–120, `SWA_START_EP=111`
in `kaggle_train_contrail_v2.ipynb`).

### What actually happened

The WR-3 cosine cycle (T_max=30, restart at epoch 91) decayed smoothly from `lr=9.97e-05`
down to `lr=5.28e-06` by epoch 116 — on schedule. Epoch 117 is missing from the recorded
history (a session interruption around that point), and when the notebook resumed at
epoch 118 the LR scheduler was **not restored from the checkpoint** (`START_LR = 1e-4`,
by design, for warm restarts) — so it jumped straight back up to `9.97e-05` instead of
continuing the decay. This amounted to an unplanned micro-restart for the last 3 epochs.
Because the in-memory `swa_model` accumulator is also not persisted across a session
restart, SWA effectively only had 3 snapshots to average (epochs 118–120) instead of the
planned 10 (111–120).

| Epoch | Train Dice | Val Dice (per-batch) | LR | Note |
|---|---|---|---|---|
| 116 | 0.7786 | **0.8343** | 5.28e-06 | Best single-checkpoint (EMA) of the whole 120-epoch run |
| 118 | 0.7633 | 0.8258 | 9.97e-05 | swa#1 — post-restart, LR back near cycle start |
| 119 | 0.7619 | 0.8221 | 9.89e-05 | swa#2 |
| 120 | 0.7608 | 0.8211 | 9.76e-05 | swa#3 |

```
SWA (3 snapshots, ep118-120) val Dice (per-batch avg): 0.8249
EMA best (ep116):                                       0.8343
Gain:                                                   -0.0094  →  EMA kept
```

### Conclusion — plateau confirmed

- SWA under-delivered here **because it only averaged 3 post-restart snapshots that were
  still mid-decay from a fresh LR reset**, not 10 converged low-LR snapshots as designed.
  Averaging weights that are still actively moving toward a minimum is not the same as
  averaging weights that are already orbiting one — this explains the negative gain
  (−0.0094), consistent with the general SWA literature (it only helps once the weights
  have actually converged).
- Even the best single checkpoint of the whole run (epoch 116, per-batch EMA 0.8343) is a
  *per-batch* metric, not directly comparable to the *global, calibrated* Dice of 0.8394
  reported for WR-2's epoch-88 checkpoint. No new global calibration was run for epoch 116
  (would require a multi-minute full-val-set GPU pass) — see the note under Final State.
- Taking the two numbers together, the honest read is: **the model has plateaued in the
  ~0.83–0.84 Dice range since WR-2**; three additional Warm Restart cycles (WR-1 → WR-2 → WR-3)
  and now SWA have not produced a clear further improvement. Further gains would likely need
  more/better-annotated data or architecture changes rather than more optimisation schedule
  tricks.

### Lessons

- **Persist LR scheduler state, not just model weights, across session restarts** — the
  intentional "fresh restart LR" design for *planned* Warm Restarts also fires
  *unintentionally* on a crash-recovery mid-cycle, corrupting an in-progress cosine decay.
- **Persist the SWA accumulator (`swa_model`, `swa_n`) alongside the checkpoint** — otherwise
  a session interruption silently shrinks the averaging window without any error or warning.

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
| `data/checkpoint_last.pt` | Full checkpoint — epoch 120, history (119 of 120 epochs logged; ep117 lost to a session interruption) |
| `data/contrail_unet_best.pt` | Best model weights — epoch 116, per-batch EMA val Dice 0.8343 (supersedes the WR-2 epoch-88/0.8394-global weights; not yet recalibrated) |
| `../images/training_curves_final.png` | Training history chart — all 120 epochs, WR-1/WR-2/WR-3 markers + SWA phase (ep118-120) |
| `../images/inference_samples.png` | Control set inference — 8 images, input / GT / prediction (not regenerated this run — see report) |
