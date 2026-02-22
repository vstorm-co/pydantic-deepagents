#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
git config --global --add safe.directory /testbed
cd /testbed
git status
git show
git -c core.fileMode=false diff aca3f825f2e4a8817190f3c885a242a285aa0dba
source /opt/miniconda3/bin/activate
conda activate testbed
python -m pip install -e .[test]
git checkout aca3f825f2e4a8817190f3c885a242a285aa0dba tests/test_domain_py.py
git apply -v - <<'EOF_114329324912'
diff --git a/tests/test_domain_py.py b/tests/test_domain_py.py
--- a/tests/test_domain_py.py
+++ b/tests/test_domain_py.py
@@ -239,6 +239,7 @@ def test_get_full_qualified_name():
 def test_parse_annotation():
     doctree = _parse_annotation("int")
     assert_node(doctree, ([pending_xref, "int"],))
+    assert_node(doctree[0], pending_xref, refdomain="py", reftype="class", reftarget="int")
 
     doctree = _parse_annotation("List[int]")
     assert_node(doctree, ([pending_xref, "List"],
@@ -266,6 +267,12 @@ def test_parse_annotation():
                           [pending_xref, "int"],
                           [desc_sig_punctuation, "]"]))
 
+    # None type makes an object-reference (not a class reference)
+    doctree = _parse_annotation("None")
+    assert_node(doctree, ([pending_xref, "None"],))
+    assert_node(doctree[0], pending_xref, refdomain="py", reftype="obj", reftarget="None")
+
+
 
 def test_pyfunction_signature(app):
     text = ".. py:function:: hello(name: str) -> str"

EOF_114329324912
: '>>>>> Start Test Output'
tox --current-env -epy39 -v -- tests/test_domain_py.py
: '>>>>> End Test Output'
git checkout aca3f825f2e4a8817190f3c885a242a285aa0dba tests/test_domain_py.py
