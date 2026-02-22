# sphinx-doc__sphinx-8265

**Repository**: sphinx-doc/sphinx
**Duration**: 603.4s
**Cost**: $0.0000
**Status**: Timed out
**Patch**: 48 lines

## Tool Calls

## Patch

```diff
diff --git a/setup.py b/setup.py
index a404f1fa5..2c6848797 100644
--- a/setup.py
+++ b/setup.py
@@ -15,22 +15,22 @@ if sys.version_info < (3, 5):
     sys.exit(1)
 
 install_requires = [
-    'sphinxcontrib-applehelp',
-    'sphinxcontrib-devhelp',
+    'sphinxcontrib-applehelp<=1.0.7',
+    'sphinxcontrib-devhelp<=1.0.5',
     'sphinxcontrib-jsmath',
-    'sphinxcontrib-htmlhelp',
-    'sphinxcontrib-serializinghtml',
-    'sphinxcontrib-qthelp',
-    'Jinja2>=2.3',
+    'sphinxcontrib-htmlhelp<=2.0.4',
+    'sphinxcontrib-serializinghtml<=1.1.9',
+    'sphinxcontrib-qthelp<=1.0.6',
+    'Jinja2<3.0',
     'Pygments>=2.0',
     'docutils>=0.12',
     'snowballstemmer>=1.1',
     'babel>=1.3',
-    'alabaster>=0.7,<0.8',
+    'alabaster>=0.7,<0.7.12',
     'imagesize',
     'requests>=2.5.0',
     'setuptools',
-    'packaging',
+    'packaging', 'markupsafe<=2.0.1',
 ]
 
 extras_require = {
diff --git a/tox.ini b/tox.ini
index a61299979..e2baccc07 100644
--- a/tox.ini
+++ b/tox.ini
@@ -28,7 +28,7 @@ setenv =
     PYTHONWARNINGS = all,ignore::ImportWarning:importlib._bootstrap_external,ignore::DeprecationWarning:site,ignore::DeprecationWarning:distutils
     PYTEST_ADDOPTS = --color yes
 commands=
-    pytest --durations 25 {posargs}
+    pytest -rA --durations 25 {posargs}
 
 [testenv:flake8]
 basepython = python3
```