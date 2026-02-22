# sphinx-doc__sphinx-10435

**Repository**: sphinx-doc/sphinx
**Duration**: 640.7s
**Cost**: $0.0000
**Status**: Timed out
**Patch**: 13 lines

## Tool Calls

## Patch

```diff
diff --git a/tox.ini b/tox.ini
index 105a02597..90ada0821 100644
--- a/tox.ini
+++ b/tox.ini
@@ -29,7 +29,7 @@ setenv =
     PYTHONWARNINGS = all
     PYTEST_ADDOPTS = {env:PYTEST_ADDOPTS:} --color yes
 commands=
-    python -X dev -X warn_default_encoding -m pytest --durations 25 {posargs}
+    python -X dev -X warn_default_encoding -m pytest -rA --durations 25 {posargs}
 
 [testenv:du-latest]
 commands =
```