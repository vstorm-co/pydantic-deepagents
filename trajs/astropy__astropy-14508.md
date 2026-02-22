# astropy__astropy-14508

**Repository**: astropy/astropy
**Duration**: 649.5s
**Cost**: $0.0000
**Status**: Timed out
**Patch**: 11 lines

## Tool Calls

## Patch

```diff
diff --git a/pyproject.toml b/pyproject.toml
index 65df5b1b77..d02c4f9eda 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,5 +1,5 @@
 [build-system]
-requires = ["setuptools",
+requires = ["setuptools==68.0.0",
             "setuptools_scm>=6.2",
             "wheel",
             "cython==0.29.30",
```