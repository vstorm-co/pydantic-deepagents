# sphinx-doc__sphinx-8638

**Repository**: sphinx-doc/sphinx
**Duration**: 604.0s
**Cost**: $0.0000
**Status**: Timed out
**Patch**: 13 lines

## Tool Calls

## Patch

```diff
diff --git a/sphinx/domains/python.py b/sphinx/domains/python.py
index 000e2e8d3..a1f13716e 100644
--- a/sphinx/domains/python.py
+++ b/sphinx/domains/python.py
@@ -354,7 +354,7 @@ class PyObject(ObjectDescription):
                             'keyword', 'kwarg', 'kwparam'),
                      typerolename='class', typenames=('paramtype', 'type'),
                      can_collapse=True),
-        PyTypedField('variable', label=_('Variables'), rolename='obj',
+        PyTypedField('variable', label=_('Variables'), rolename=None,
                      names=('var', 'ivar', 'cvar'),
                      typerolename='class', typenames=('vartype',),
                      can_collapse=True),
```