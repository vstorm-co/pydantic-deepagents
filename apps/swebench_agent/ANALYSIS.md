# SWE-bench Evaluation Analysis

**Model**: `openrouter:minimax/minimax-m2.5` (bez reasoning — bugi w konfiguracji)
**Date**: 2026-02-22
**Dataset**: SWE-bench Verified (500 instances)

## Summary

| Category | Count | % |
|----------|-------|---|
| Resolved | 229 | 45.8% |
| Unresolved (wrong patch) | 170 | 34.0% |
| Empty patch (no edits) | 54 | 10.8% |
| Errors (eval infra) | 33 | 6.6% |
| Not submitted | 14 | 2.8% |
| **Total** | **500** | |

**Expected**: ~75.8% (MiniMax M2.5 leaderboard score)

## Known Bugs in This Run

Ten run byl wykonany PRZED fixami. Znane problemy:

1. **Wrong working_dir** — agent dostawal sciezke hosta (`/Users/.../pydantic-deep`) zamiast `/testbed`
2. **Skills disabled** — `non_interactive=True` wylaczalo skills (naprawione: `effective_skills = include_skills`)
3. **Reasoning not enabled** — `--reasoning` flag nie byl uzyty, MiniMax M2.5 potrzebuje reasoning mode
4. **LocalContextToolset crash** — probowal czytac git info z `/testbed` na hoscie (naprawione: `include_local_context=False`)
5. **Skills not in wheel** — `.pydantic-deep/skills/` nie bylo w pip install (naprawione: bundled_skills fallback)

---

## Category 1: Errors (33 instances)

**Root cause**: Docker image not found during **evaluation** (not agent). The swebench harness
tries to pull `swebench/sweb.eval.x86_64.{id}:latest` but these images don't exist for most
sympy instances. This is an infrastructure issue, not an agent problem.

**Breakdown**: 31x sympy, 1x django, 1x pytest

### Sample instances to re-run

```bash
# 1. django__django-11400 (jedyny django error — ciekawy)
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -i django__django-11400 \
    --timeout 600 -v

# 2. pytest-dev__pytest-7236 (jedyny pytest error)
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -i pytest-dev__pytest-7236 \
    --timeout 600 -v

# 3. sympy__sympy-18199
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -i sympy__sympy-18199 \
    --timeout 600 -v

# 4. sympy__sympy-20154
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -i sympy__sympy-20154 \
    --timeout 600 -v

# 5. sympy__sympy-24562
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -i sympy__sympy-24562 \
    --timeout 600 -v
```

---

## Category 2: Empty Patches (54 instances)

**Root cause**: Agent ran but produced no `git diff`. Prawdopodobnie przez wrong working_dir
agent nie mogl znalezc plikow do edycji. Z fixami (correct `/testbed`, skills, reasoning)
ta kategoria powinna sie najbardziej poprawic.

**Breakdown**: 13x django, 20x matplotlib, 2x seaborn, 3x xarray, 5x pytest, 8x scikit-learn, 3x sympy

### Sample instances to re-run

```bash
# 1. django__django-16950 (z README, popularny benchmark instance)
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -i django__django-16950 \
    --timeout 600 -v

# 2. matplotlib__matplotlib-25311
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -i matplotlib__matplotlib-25311 \
    --timeout 600 -v

# 3. scikit-learn__scikit-learn-13142
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -i scikit-learn__scikit-learn-13142 \
    --timeout 600 -v

# 4. pytest-dev__pytest-5787
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -i pytest-dev__pytest-5787 \
    --timeout 600 -v

# 5. pydata__xarray-4695
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -i pydata__xarray-4695 \
    --timeout 600 -v
```

---

## Category 3: Unresolved (170 instances)

**Root cause**: Agent produced a patch but it was wrong — tests still fail after applying it.
Z fixami (reasoning, skills) jakos patchow powinna wzrosnac.

**Breakdown**: 18x astropy, 62x django, 3x matplotlib, 3x psf/requests, 7x xarray,
6x pylint, 3x pytest, 12x scikit-learn, 39x sphinx, 13x sympy

### Sample instances to re-run

```bash
# 1. django__django-10097 (prosty django)
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -i django__django-10097 \
    --timeout 600 -v

# 2. django__django-11087
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -i django__django-11087 \
    --timeout 600 -v

# 3. scikit-learn__scikit-learn-13124
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -i scikit-learn__scikit-learn-13124 \
    --timeout 600 -v

# 4. sphinx-doc__sphinx-8265
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -i sphinx-doc__sphinx-8265 \
    --timeout 600 -v

# 5. sympy__sympy-13031
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -i sympy__sympy-13031 \
    --timeout 600 -v
```

---

## Quick batch: all 15 instances at once

```bash
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -i django__django-11400 \
    -i pytest-dev__pytest-7236 \
    -i sympy__sympy-18199 \
    -i sympy__sympy-20154 \
    -i sympy__sympy-24562 \
    -i django__django-16950 \
    -i matplotlib__matplotlib-25311 \
    -i scikit-learn__scikit-learn-13142 \
    -i pytest-dev__pytest-5787 \
    -i pydata__xarray-4695 \
    -i django__django-10097 \
    -i django__django-11087 \
    -i scikit-learn__scikit-learn-13124 \
    -i sphinx-doc__sphinx-8265 \
    -i sympy__sympy-13031 \
    --timeout 600 \
    --trajs-dir trajs-debug/ \
    -o debug-predictions.jsonl \
    -v
```

---

## All Instance IDs

### Empty Patches (54)

django__django-10554, django__django-11149, django__django-11179, django__django-11734,
django__django-12663, django__django-13513, django__django-14351, django__django-15280,
django__django-16032, django__django-16263, django__django-16315, django__django-16661,
django__django-16950, matplotlib__matplotlib-13989, matplotlib__matplotlib-14623,
matplotlib__matplotlib-20488, matplotlib__matplotlib-20826, matplotlib__matplotlib-21568,
matplotlib__matplotlib-22865, matplotlib__matplotlib-22871, matplotlib__matplotlib-23299,
matplotlib__matplotlib-23476, matplotlib__matplotlib-24026, matplotlib__matplotlib-24177,
matplotlib__matplotlib-24627, matplotlib__matplotlib-24970, matplotlib__matplotlib-25311,
matplotlib__matplotlib-25332, matplotlib__matplotlib-25479, matplotlib__matplotlib-25775,
matplotlib__matplotlib-25960, matplotlib__matplotlib-26208, matplotlib__matplotlib-26342,
mwaskom__seaborn-3069, mwaskom__seaborn-3187, pydata__xarray-3993, pydata__xarray-4695,
pydata__xarray-6599, pytest-dev__pytest-10051, pytest-dev__pytest-10356,
pytest-dev__pytest-5787, pytest-dev__pytest-6197, pytest-dev__pytest-8399,
scikit-learn__scikit-learn-10908, scikit-learn__scikit-learn-13142,
scikit-learn__scikit-learn-13439, scikit-learn__scikit-learn-14629,
scikit-learn__scikit-learn-14894, scikit-learn__scikit-learn-14983,
scikit-learn__scikit-learn-26323, scikit-learn__scikit-learn-9288,
sympy__sympy-19040, sympy__sympy-22080, sympy__sympy-24661

### Errors (33)

django__django-11400, pytest-dev__pytest-7236, sympy__sympy-18199, sympy__sympy-18211,
sympy__sympy-18698, sympy__sympy-18763, sympy__sympy-19346, sympy__sympy-19495,
sympy__sympy-19637, sympy__sympy-19783, sympy__sympy-19954, sympy__sympy-20154,
sympy__sympy-20428, sympy__sympy-20438, sympy__sympy-20590, sympy__sympy-20801,
sympy__sympy-20916, sympy__sympy-21379, sympy__sympy-21596, sympy__sympy-21612,
sympy__sympy-21847, sympy__sympy-21930, sympy__sympy-22456, sympy__sympy-22714,
sympy__sympy-22914, sympy__sympy-23262, sympy__sympy-23413, sympy__sympy-23534,
sympy__sympy-23824, sympy__sympy-23950, sympy__sympy-24066, sympy__sympy-24213,
sympy__sympy-24562

### Unresolved (170)

astropy__astropy-12907, astropy__astropy-13033, astropy__astropy-13236,
astropy__astropy-13398, astropy__astropy-13453, astropy__astropy-13579,
astropy__astropy-13977, astropy__astropy-14096, astropy__astropy-14182,
astropy__astropy-14369, astropy__astropy-14508, astropy__astropy-14539,
astropy__astropy-14598, astropy__astropy-14995, astropy__astropy-7336,
astropy__astropy-7606, astropy__astropy-8707, astropy__astropy-8872,
django__django-10097, django__django-10999, django__django-11087,
django__django-11265, django__django-11333, django__django-11477,
django__django-11728, django__django-11740, django__django-11820,
django__django-11885, django__django-11964, django__django-12193,
django__django-12209, django__django-12273, django__django-12308,
django__django-12325, django__django-12406, django__django-13112,
django__django-13195, django__django-13212, django__django-13344,
django__django-13512, django__django-13590, django__django-13794,
django__django-13964, django__django-14007, django__django-14011,
django__django-14017, django__django-14034, django__django-14053,
django__django-14140, django__django-14155, django__django-14311,
django__django-14315, django__django-14376, django__django-14534,
django__django-14631, django__django-14792, django__django-15022,
django__django-15098, django__django-15127, django__django-15128,
django__django-15161, django__django-15252, django__django-15503,
django__django-15554, django__django-15563, django__django-15629,
django__django-15695, django__django-15732, django__django-15741,
django__django-15916, django__django-15973, django__django-16082,
django__django-16256, django__django-16454, django__django-16502,
django__django-16631, django__django-16667, django__django-16819,
django__django-16877, django__django-17029, matplotlib__matplotlib-24870,
matplotlib__matplotlib-25287, matplotlib__matplotlib-26466,
psf__requests-2931, psf__requests-5414, psf__requests-6028,
pydata__xarray-4075, pydata__xarray-4687, pydata__xarray-6461,
pydata__xarray-6744, pydata__xarray-6938, pydata__xarray-6992,
pydata__xarray-7229, pylint-dev__pylint-4551, pylint-dev__pylint-4604,
pylint-dev__pylint-4661, pylint-dev__pylint-4970, pylint-dev__pylint-6528,
pylint-dev__pylint-7080, pytest-dev__pytest-5631, pytest-dev__pytest-5840,
pytest-dev__pytest-7324, scikit-learn__scikit-learn-10297,
scikit-learn__scikit-learn-12682, scikit-learn__scikit-learn-12973,
scikit-learn__scikit-learn-13124, scikit-learn__scikit-learn-13496,
scikit-learn__scikit-learn-14087, scikit-learn__scikit-learn-14710,
scikit-learn__scikit-learn-25232, scikit-learn__scikit-learn-25747,
scikit-learn__scikit-learn-25931, scikit-learn__scikit-learn-25973,
scikit-learn__scikit-learn-26194, sphinx-doc__sphinx-10323,
sphinx-doc__sphinx-10435, sphinx-doc__sphinx-10449, sphinx-doc__sphinx-10466,
sphinx-doc__sphinx-10614, sphinx-doc__sphinx-10673, sphinx-doc__sphinx-11445,
sphinx-doc__sphinx-11510, sphinx-doc__sphinx-7440, sphinx-doc__sphinx-7454,
sphinx-doc__sphinx-7462, sphinx-doc__sphinx-7590, sphinx-doc__sphinx-7748,
sphinx-doc__sphinx-7757, sphinx-doc__sphinx-7889, sphinx-doc__sphinx-7910,
sphinx-doc__sphinx-7985, sphinx-doc__sphinx-8035, sphinx-doc__sphinx-8056,
sphinx-doc__sphinx-8120, sphinx-doc__sphinx-8265, sphinx-doc__sphinx-8269,
sphinx-doc__sphinx-8459, sphinx-doc__sphinx-8475, sphinx-doc__sphinx-8548,
sphinx-doc__sphinx-8551, sphinx-doc__sphinx-8593, sphinx-doc__sphinx-8595,
sphinx-doc__sphinx-8621, sphinx-doc__sphinx-8721, sphinx-doc__sphinx-9229,
sphinx-doc__sphinx-9230, sphinx-doc__sphinx-9258, sphinx-doc__sphinx-9320,
sphinx-doc__sphinx-9367, sphinx-doc__sphinx-9461, sphinx-doc__sphinx-9591,
sphinx-doc__sphinx-9602, sphinx-doc__sphinx-9658, sphinx-doc__sphinx-9673,
sphinx-doc__sphinx-9698, sphinx-doc__sphinx-9711, sympy__sympy-12096,
sympy__sympy-12481, sympy__sympy-12489, sympy__sympy-13031,
sympy__sympy-13372, sympy__sympy-13757, sympy__sympy-13798,
sympy__sympy-13852, sympy__sympy-13974, sympy__sympy-14248,
sympy__sympy-14976, sympy__sympy-15599, sympy__sympy-16597,
sympy__sympy-17630
