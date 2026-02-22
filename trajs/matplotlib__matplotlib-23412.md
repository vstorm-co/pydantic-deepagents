# matplotlib__matplotlib-23412

**Repository**: matplotlib/matplotlib
**Duration**: 635.3s
**Cost**: $0.0000
**Status**: Timed out
**Patch**: 16 lines

## Tool Calls

## Patch

```diff
diff --git a/lib/matplotlib/patches.py b/lib/matplotlib/patches.py
index e062249589..0c893aac3a 100644
--- a/lib/matplotlib/patches.py
+++ b/lib/matplotlib/patches.py
@@ -586,10 +586,7 @@ class Patch(artist.Artist):
         # docstring inherited
         if not self.get_visible():
             return
-        # Patch has traditionally ignored the dashoffset.
-        with cbook._setattr_cm(
-                 self, _dash_pattern=(0, self._dash_pattern[1])), \
-             self._bind_draw_path_function(renderer) as draw_path:
+        with self._bind_draw_path_function(renderer) as draw_path:
             path = self.get_path()
             transform = self.get_transform()
             tpath = transform.transform_path_non_affine(path)
```