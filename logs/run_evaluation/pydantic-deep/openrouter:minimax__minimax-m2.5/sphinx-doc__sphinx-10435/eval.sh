#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git -c core.fileMode=false diff f1061c012e214f16fd8790dec3c283d787e3daa8
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .[test]
git checkout f1061c012e214f16fd8790dec3c283d787e3daa8 tests/test_build_latex.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/test_build_latex.py b/tests/test_build_latex.py
--- a/tests/test_build_latex.py
+++ b/tests/test_build_latex.py
@@ -1623,7 +1623,7 @@ def test_latex_code_role(app):
         r'\PYG{p}{)}'
         r'\PYG{p}{:} '
         r'\PYG{k}{pass}')
-    assert (r'Inline \sphinxcode{\sphinxupquote{' + '\n' +
-            common_content + '\n}} code block') in content
+    assert (r'Inline \sphinxcode{\sphinxupquote{%' + '\n' +
+            common_content + '%\n}} code block') in content
     assert (r'\begin{sphinxVerbatim}[commandchars=\\\{\}]' +
             '\n' + common_content + '\n' + r'\end{sphinxVerbatim}') in content

EOF_114329324912
: '>>>>> Start Test Output'
tox --current-env -epy39 -v -- tests/test_build_latex.py
: '>>>>> End Test Output'
git checkout f1061c012e214f16fd8790dec3c283d787e3daa8 tests/test_build_latex.py
