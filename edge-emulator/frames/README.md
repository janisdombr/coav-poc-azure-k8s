# GVCCS held-out validation frames

These images are a held-out validation subset (split `seed=42`, identical to
`edge-pi/python/train.py`) of the **GVCCS — Ground Visible Camera Contrail
Sequences** dataset, used by the emulator's ground-camera verification channel.

## Attribution (required by licence)

- **Dataset:** GVCCS — Ground Visible Camera Contrail Sequences (EUROCONTROL MUAC, Brétigny-sur-Orge)
- **Source:** Zenodo — https://doi.org/10.5281/zenodo.15743988
- **Licence:** Creative Commons Attribution 4.0 International (CC BY 4.0)
  — https://creativecommons.org/licenses/by/4.0/

Redistribution is permitted under CC BY 4.0 provided the creators are credited,
as above. No changes were made to the source images (they are only downscaled at
runtime by the emulator for the camera payload).

## Regenerate

```sh
cd edge-emulator && python prepare_val_frames.py
```
