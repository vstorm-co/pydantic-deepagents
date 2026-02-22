# django__django-15103

**Repository**: django/django
**Duration**: 257.5s
**Cost**: $0.0000
**Status**: Completed
**Patch**: 50 lines

## Tool Calls

### Step 1: `grep`

```
{}
```

**Result** (`grep`):

```
Files containing 'def json_script':
  /testbed/django/template/defaultfilters.py
  /testbed/django/utils/html.py
```

### Step 2: `read_file`

```
{}
```

**Result** (`read_file`):

```
1:55|"""HTML utilities suitable for global use."""
2:d4|
3:4a|import html
4:39|import json
5:a7|import re
6:a6|from html.parser import HTMLParser
7:a8|from urllib.parse import (
8:0f|    parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit,
9:93|)
10:d4|
11:2c|from django.utils.encoding import punycode
12:66|from django.utils.functional import Promise, keep_lazy, keep_lazy_text
13:20|from django.utils.http import RFC3986_GENDELIMS, RFC3986_SUBDELIMS
14:c4|from django.utils.regex_helper import _lazy_re_compile
15:7d|from django.utils.safestring import SafeData, SafeString, mark_safe
16:8f|from django.utils.text import normalize_newlines
17:d4|
18:d4|
19:5d|@keep_lazy(str, SafeString)
20:56|def escape(text):
21:fd|    """
22:64|    Return the given text with ampersands, quotes and angle brackets encoded
23:42|    for use in HTML.
24:d4|
25:e2|    Always escape input, even if it's already escaped and marked as such.
26:e0|    This may result in double-escaping. If this is a concern, use
27:c0|    conditional_escape() instead.
28:fd|    """
29:26|    return mark_safe(html.escape(str(text)))
30:d4|
31:d4|
32:75|_js_escapes = {
33:d3|    ord('\\'): '\\u005C',
34:74|    ord('\''): '\\u0027',
35:8a|    ord('"'): '\\u0022',
36:0a|    ord('>'): '\\u003E',
37:3f|    ord('<'): '\\u003C',
38:be|    ord('&'): '\\u0026',
39:c6|    ord('='): '\\u003D',
40:51|    ord('-'): '\\u002D',
41:07|    ord(';'): '\\u003B',
42:99|    ord('`'): '\\u0060',
43:33|    ord('\u2028'): '\\u2028',
44:5f|    ord('\u2029'): '\\u2029'
45:cb|}
46:d4|
47:21|# Escape every ASCII character with a value less than 32.
48:08|_js_escapes.update((ord('%c' % z), '\\u%04X' % z) for z in range(32))
49:d4|
50:d4|
51:5d|@keep_lazy(str, SafeString)
52:b3|def escapejs(value):
53:15|    """Hex encode characters for use in JavaScript strings."""
54:49|    return mark_safe(str(value).translate(_js_escapes))
55:d4|
56:d4|
57:9e|_json_script_escapes = {
58:0a|    ord('>'): '\\u003E',
59:3f|    ord('<'): '\\u003C',
...
```

### Step 3: `grep`

```
{}
```

**Result** (`grep`):

```
No matches for 'json_script'
```

### Step 4: `grep`

```
{}
```

**Result** (`grep`):

```
No matches for 'json_script'
```

### Step 5: `grep`

```
{}
```

**Result** (`grep`):

```
No matches for 'json_script'
```

### Step 6: `grep`

```
{}
```

**Result** (`grep`):

```
No matches for 'json_script'
```

### Step 7: `execute`

```
{}
```

**Result** (`execute`):

```
/testbed/django/utils/html.py:_json_script_escapes = {
/testbed/django/utils/html.py:def json_script(value, element_id):
/testbed/django/utils/html.py:    json_str = json.dumps(value, cls=DjangoJSONEncoder).translate(_json_script_escapes)
/testbed/django/template/defaultfilters.py:    json_script as _json_script, linebreaks, strip_tags, urlize as _urlize,
/testbed/django/template/defaultfilters.py:def json_script(value, element_id):
/testbed/django/template/defaultfilters.py:    return _json_script(value, element_id)

```

### Step 8: `grep`

```
{}
```

**Result** (`grep`):

```
No matches for 'json_script'
```

### Step 9: `read_file`

```
{}
```

**Result** (`read_file`):

```
1:66|"""Default variable filters."""
2:03|import random as random_module
3:a7|import re
4:69|import types
5:8e|from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation
6:61|from functools import wraps
7:43|from operator import itemgetter
8:48|from pprint import pformat
9:ff|from urllib.parse import quote
10:d4|
11:94|from django.utils import formats
12:0c|from django.utils.dateformat import format, time_format
13:5d|from django.utils.encoding import iri_to_uri
14:f8|from django.utils.html import (
15:5f|    avoid_wrapping, conditional_escape, escape, escapejs,
16:bf|    json_script as _json_script, linebreaks, strip_tags, urlize as _urlize,
17:93|)
18:24|from django.utils.safestring import SafeData, mark_safe
19:a1|from django.utils.text import (
20:f9|    Truncator, normalize_newlines, phone2numeric, slugify as _slugify, wrap,
21:93|)
22:8a|from django.utils.timesince import timesince, timeuntil
23:a4|from django.utils.translation import gettext, ngettext
24:d4|
25:61|from .base import Variable, VariableDoesNotExist
26:6e|from .library import Library
27:d4|
28:df|register = Library()
29:d4|
30:d4|
31:b8|#######################
32:f6|# STRING DECORATOR    #
33:b8|#######################
34:d4|
35:84|def stringfilter(func):
36:fd|    """
37:94|    Decorator for filters which should only receive strings. The object
38:f1|    passed as the first positional argument will be converted to a string.
39:fd|    """
40:25|    def _dec(*args, **kwargs):
41:e3|        args = list(args)
42:92|        args[0] = str(args[0])
43:44|        if (isinstance(args[0], SafeData) and
44:39|                getattr(_dec._decorated_function, 'is_safe', False)):
45:83|            return mark_safe(func(*args, **kwargs))
46:64|        return func(*args, **kwargs)
47:d4|
48:53|    # Include a reference to the real function (used to check original
49:4f|    # arguments by the template parser, and to bear the 'is_safe' attribute
50:c9|    # when multiple decorators are applied).
51...
```

### Step 10: `execute`

```
{}
```

**Result** (`execute`):

```
/testbed/tests/utils_tests/test_html.py:    conditional_escape, escape, escapejs, format_html, html_safe, json_script,
/testbed/tests/utils_tests/test_html.py:    def test_json_script(self):
/testbed/tests/utils_tests/test_html.py:                self.assertEqual(json_script(arg, 'test_id'), expected)
/testbed/tests/template_tests/filter_tests/test_json_script.py:    @setup({'json-tag01': '{{ value|json_script:"test_id" }}'})

```

### Step 11: `read_file`

```
{}
```

**Result** (`read_file`):

```
Error: Offset 730 exceeds file length (279 lines)
```

### Step 12: `grep`

```
{}
```

**Result** (`grep`):

```
No matches for 'json_script'
```

### Step 13: `execute`

```
{}
```

**Result** (`execute`):

```
7:    conditional_escape, escape, escapejs, format_html, html_safe, json_script,
154:    def test_json_script(self):
174:                self.assertEqual(json_script(arg, 'test_id'), expected)

```

### Step 14: `read_file`

```
{}
```

**Result** (`read_file`):

```
151:b8|                self.check_output(escapejs, value, output)
152:44|                self.check_output(escapejs, lazystr(value), output)
153:d4|
154:c6|    def test_json_script(self):
155:5c|        tests = (
156:96|            # "<", ">" and "&" are quoted inside JSON strings
157:15|            (('&<>', '<script id="test_id" type="application/json">"\\u0026\\u003C\\u003E"</script>')),
158:c8|            # "<", ">" and "&" are quoted inside JSON objects
159:ef|            (
160:0a|                {'a': '<script>test&ing</script>'},
161:ef|                '<script id="test_id" type="application/json">'
162:ea|                '{"a": "\\u003Cscript\\u003Etest\\u0026ing\\u003C/script\\u003E"}</script>'
163:01|            ),
164:31|            # Lazy strings are quoted
165:f6|            (lazystr('&<>'), '<script id="test_id" type="application/json">"\\u0026\\u003C\\u003E"</script>'),
166:ef|            (
167:5d|                {'a': lazystr('<script>test&ing</script>')},
168:ef|                '<script id="test_id" type="application/json">'
169:ea|                '{"a": "\\u003Cscript\\u003Etest\\u0026ing\\u003C/script\\u003E"}</script>'
170:01|            ),
171:41|        )
172:3b|        for arg, expected in tests:
173:fe|            with self.subTest(arg=arg):
174:d3|                self.assertEqual(json_script(arg, 'test_id'), expected)
175:d4|
176:93|    def test_smart_urlquote(self):
177:92|        items = (
178:cf|            ('http://öäü.com/', 'http://xn--4ca9at.com/'),
179:0d|            ('http://öäü.com/öäü/', 'http://xn--4ca9at.com/%C3%B6%C3%A4%C3%BC/'),
180:e4|            # Everything unsafe is quoted, !*'();:@&=+$,/?#[]~ is considered

... (99 more lines)
```

### Step 15: `execute`

```
{}
```

**Result** (`execute`):

```
from django.test import SimpleTestCase

from ..utils import setup


class JsonScriptTests(SimpleTestCase):

    @setup({'json-tag01': '{{ value|json_script:"test_id" }}'})
    def test_basic(self):
        output = self.engine.render_to_string(
            'json-tag01',
            {'value': {'a': 'testing\r\njson \'string" <b>escaping</b>'}}
        )
        self.assertEqual(
            output,
            '<script id="test_id" type="application/json">'
            '{"a": "testing\\r\\njson \'string\\" \\u003Cb\\u003Eescaping\\u003C/b\\u003E"}'
            '</script>'
        )

```

### Step 16: `hashline_edit`

```
{}
```

**Result** (`hashline_edit`):

```
Error: Hash mismatch at line 64: expected '64', got '98'. File may have changed — re-read it first.
```

### Step 17: `read_file`

```
{}
```

**Result** (`read_file`):

```
61:cb|}
62:d4|
63:d4|
64:98|def json_script(value, element_id):
65:fd|    """
66:85|    Escape all the HTML/XML special characters with their unicode escapes, so
67:99|    value is safe to be output anywhere except for inside a tag attribute. Wrap
68:e0|    the escaped JSON in a script tag.
69:fd|    """
70:35|    from django.core.serializers.json import DjangoJSONEncoder
71:d6|    json_str = json.dumps(value, cls=DjangoJSONEncoder).translate(_json_script_escapes)
72:b2|    return format_html(
73:1b|        '<script id="{}" type="application/json">{}</script>',
74:ee|        element_id, mark_safe(json_str)
75:5c|    )
76:d4|
77:d4|
78:5f|def conditional_escape(text):
79:fd|    """
80:39|    Similar to escape(), except that it doesn't operate on pre-escaped strings.

... (324 more lines)
```

### Step 18: `hashline_edit`

```
{}
```

**Result** (`hashline_edit`):

```
Error: Hash mismatch at line 64: expected '64', got '98'. File may have changed — re-read it first.
```

### Step 19: `execute`

```
{}
```

**Result** (`execute`):

```
}


def json_script(value, element_id):
    """
    Escape all the HTML/XML special characters with their unicode escapes, so
    value is safe to be output anywhere except for inside a tag attribute. Wrap
    the escaped JSON in a script tag.
    """
    from django.core.serializers.json import DjangoJSONEncoder
    json_str = json.dumps(value, cls=DjangoJSONEncoder).translate(_json_script_escapes)
    return format_html(
        '<script id="{}" type="application/json">{}</script>',
        element_id, mark_safe(json_str)
    )


def conditional_escape(text):
    """
    Similar to escape(), except that it doesn't operate on pre-escaped strings.

```

### Step 20: `execute`

```
{}
```

**Result** (`execute`):

```
def json_script(value, element_id):
    """
    Escape all the HTML/XML special characters with their unicode escapes, so
    value is safe to be output anywhere except for inside a tag attribute. Wrap
    the escaped JSON in a script tag.
    """
    from django.core.serializers.json import DjangoJSONEncoder
    json_str = json.dumps(value, cls=DjangoJSONEncoder).translate(_json_script_escapes)
    return format_html(
        '<script id="{}" type="application/json">{}</script>',
        element_id, mark_safe(json_str)
    )


```

### Step 21: `read_file`

```
{}
```

**Result** (`read_file`):

```
61:cb|}
62:d4|
63:d4|
64:98|def json_script(value, element_id):
65:fd|    """
66:85|    Escape all the HTML/XML special characters with their unicode escapes, so
67:99|    value is safe to be output anywhere except for inside a tag attribute. Wrap
68:e0|    the escaped JSON in a script tag.
69:fd|    """
70:35|    from django.core.serializers.json import DjangoJSONEncoder
71:d6|    json_str = json.dumps(value, cls=DjangoJSONEncoder).translate(_json_script_escapes)
72:b2|    return format_html(
73:1b|        '<script id="{}" type="application/json">{}</script>',
74:ee|        element_id, mark_safe(json_str)
75:5c|    )
76:d4|
77:d4|
78:5f|def conditional_escape(text):
79:fd|    """
80:39|    Similar to escape(), except that it doesn't operate on pre-escaped strings.

... (324 more lines)
```

### Step 22: `hashline_edit`

```
{}
```

**Result** (`hashline_edit`):

```
Edited /testbed/django/utils/html.py: Replaced 12 line(s) with 15 line(s) at line 64
```

### Step 23: `read_file`

```
{}
```

**Result** (`read_file`):

```
61:cb|}
62:d4|
63:d4|
64:ae|def json_script(value, element_id=None Escape all the HTML/XML special characters with their unicode escapes, so
65:f0|    value is safe to be output anywhere except for):
66:fd|    """
67:30|    inside a tag attribute. Wrap
68:e0|    the escaped JSON in a script tag.
69:fd|    """
70:35|    from django.core.serializers.json import DjangoJSONEncoder
71:d6|    json_str = json.dumps(value, cls=DjangoJSONEncoder).translate(_json_script_escapes)
72:90|    if element_id:
73:99|        template = '<script id="{}" type="application/json">{}</script>'
74:d4|        args = (element_id, mark_safe(json_str))
75:ef|    else:
76:c4|        template = '<script type="application/json">{}</script>'
77:76|        args = (mark_safe(json_str),)
78:98|    return format_html(template, *args)
79:d4|
80:d4|

... (327 more lines)
```

### Step 24: `hashline_edit`

```
{}
```

**Result** (`hashline_edit`):

```
Error: Hash mismatch at line 78: expected '78', got '98'. File may have changed — re-read it first.
```

### Step 25: `read_file`

```
{}
```

**Result** (`read_file`):

```
61:cb|}
62:d4|
63:d4|
64:ae|def json_script(value, element_id=None Escape all the HTML/XML special characters with their unicode escapes, so
65:f0|    value is safe to be output anywhere except for):
66:fd|    """
67:30|    inside a tag attribute. Wrap
68:e0|    the escaped JSON in a script tag.
69:fd|    """
70:35|    from django.core.serializers.json import DjangoJSONEncoder
71:d6|    json_str = json.dumps(value, cls=DjangoJSONEncoder).translate(_json_script_escapes)
72:90|    if element_id:
73:99|        template = '<script id="{}" type="application/json">{}</script>'
74:d4|        args = (element_id, mark_safe(json_str))
75:ef|    else:
76:c4|        template = '<script type="application/json">{}</script>'
77:76|        args = (mark_safe(json_str),)
78:98|    return format_html(template, *args)
79:d4|
80:d4|
81:5f|def conditional_escape(text):
82:fd|    """
83:39|    Similar to escape(), except that it doesn't operate on pre-escaped strings.
84:d4|
85:77|    This function relies on the __html__ convention used both by Django's

... (322 more lines)
```

### Step 26: `execute`

```
{}
```

**Result** (`execute`):

```

```

### Step 27: `execute`

```
{}
```

**Result** (`execute`):

```

```

### Step 28: `execute`

```
{}
```

**Result** (`execute`):

```


def conditional_escape(text):
    """
    Similar to escape(), except that it doesn't operate on pre-escaped strings.

    This function relies on the __html__ convention used both by Django's
    SafeData class and by third-party libraries like markupsafe.
    """
    if isinstance(text, Promise):
        text = str(text)
    if hasattr(text, '__html__'):
        return text.__html__()
    else:
        return escape(text)


def format_html(format_string, *args, **kwargs):
    """
    Similar to str.format, but pass all arguments through conditional_escape(),
    and call mark_safe() on the result. This function should be used instead
    of str.format or % interpolation to build up small HTML fragments.

```

### Step 29: `execute`

```
{}
```

**Result** (`execute`):

```

```

### Step 30: `execute`

```
{}
```

**Result** (`execute`):

```

```

### Step 31: `execute`

```
{}
```

**Result** (`execute`):

```
    ord('&'): '\\u0026',
}



def json_script(value, element_id=None):
    """
    Escape all the HTML/XML special characters with their unicode escapes, so
    value is safe to be output anywhere except for inside a tag attribute. Wrap
    the escaped JSON in a script tag.
    """
    from django.core.serializers.json import DjangoJSONEncoder
    json_str = json.dumps(value, cls=DjangoJSONEncoder).translate(_json_script_escapes)
    if element_id:
        template = '<script id="{}" type="application/json">{}</script>'
        args = (element_id, mark_safe(json_str))
    else:
        template = '<script type="application/json">{}</script>'
        args = (mark_safe(json_str),)
    return format_html(template, *args)



def conditional_escape(text):
    """
    Similar to escape(), except that it doesn't operate on pre-escaped strings.

    This function relies on the __html__ convention used both by Django's
    SafeData class and by third-party libraries like markupsafe.
    """
    if isinstance(text, Promise):

```

### Step 32: `execute`

```
{}
```

**Result** (`execute`):

```

```

### Step 33: `read_file`

```
{}
```

**Result** (`read_file`):

```
61:cb|}
62:d4|
63:d4|
64:d4|
65:45|def json_script(value, element_id=None):
66:fd|    """
67:85|    Escape all the HTML/XML special characters with their unicode escapes, so
68:99|    value is safe to be output anywhere except for inside a tag attribute. Wrap
69:e0|    the escaped JSON in a script tag.
70:fd|    """
71:35|    from django.core.serializers.json import DjangoJSONEncoder
72:d6|    json_str = json.dumps(value, cls=DjangoJSONEncoder).translate(_json_script_escapes)
73:90|    if element_id:
74:99|        template = '<script id="{}" type="application/json">{}</script>'
75:d4|        args = (element_id, mark_safe(json_str))
76:ef|    else:
77:c4|        template = '<script type="application/json">{}</script>'
78:76|        args = (mark_safe(json_str),)
79:98|    return format_html(template, *args)
80:d4|
81:d4|
82:d4|
83:5f|def conditional_escape(text):
84:fd|    """
85:39|    Similar to escape(), except that it doesn't operate on pre-escaped strings.

... (324 more lines)
```

### Step 34: `read_file`

```
{}
```

**Result** (`read_file`):

```
83:d4|
84:d4|
85:6a|@register.filter(is_safe=True)
86:98|def json_script(value, element_id):
87:fd|    """
88:d0|    Output value JSON-encoded, wrapped in a <script type="application/json">
89:e8|    tag.
90:fd|    """
91:96|    return _json_script(value, element_id)
92:d4|
93:d4|
94:6a|@register.filter(is_safe=True)
95:6d|def floatformat(text, arg=-1):
96:fd|    """
97:70|    Display a float to a specified number of decimal places.

... (847 more lines)
```

### Step 35: `hashline_edit`

```
{}
```

**Result** (`hashline_edit`):

```
Error: Hash mismatch at line 85: expected '98', got '6a'. File may have changed — re-read it first.
```

### Step 36: `read_file`

```
{}
```

**Result** (`read_file`):

```
83:d4|
84:d4|
85:6a|@register.filter(is_safe=True)
86:98|def json_script(value, element_id):
87:fd|    """
88:d0|    Output value JSON-encoded, wrapped in a <script type="application/json">
89:e8|    tag.
90:fd|    """
91:96|    return _json_script(value, element_id)
92:d4|
93:d4|
94:6a|@register.filter(is_safe=True)
95:6d|def floatformat(text, arg=-1):
96:fd|    """
97:70|    Display a float to a specified number of decimal places.

... (847 more lines)
```

### Step 37: `hashline_edit`

```
{}
```

**Result** (`hashline_edit`):

```
Edited /testbed/django/template/defaultfilters.py: Replaced 7 line(s) at line 85
```

### Step 38: `read_file`

```
{}
```

**Result** (`read_file`):

```
83:d4|
84:d4|
85:6a|@register.filter(is_safe=True)
86:45|def json_script(value, element_id=None):
87:fd|    """
88:d0|    Output value JSON-encoded, wrapped in a <script type="application/json">
89:55|    tag (with an optional id).
90:fd|    """
91:96|    return _json_script(value, element_id)
92:d4|
93:d4|
94:6a|@register.filter(is_safe=True)
95:6d|def floatformat(text, arg=-1):
96:fd|    """
97:70|    Display a float to a specified number of decimal places.

... (847 more lines)
```

### Step 39: `execute`

```
{}
```

**Result** (`execute`):

```
Command failed (exit code 1):
Traceback (most recent call last):
  File "<string>", line 5, in <module>
  File "/testbed/django/utils/html.py", line 71, in json_script
    from django.core.serializers.json import DjangoJSONEncoder
  File "/testbed/django/core/serializers/__init__.py", line 22, in <module>
    from django.conf import settings
  File "/testbed/django/conf/__init__.py", line 19, in <module>
    from django.utils.deprecation import RemovedInDjango50Warning
  File "/testbed/django/utils/deprecation.py", line 5, in <module>
    from asgiref.sync import sync_to_async
ModuleNotFoundError: No module named 'asgiref'

```

### Step 40: `execute`

```
{}
```

**Result** (`execute`):

```
WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv

```

### Step 41: `execute`

```
{}
```

**Result** (`execute`):

```
With ID: <script id="my_id" type="application/json">{"key": "value"}</script>
Without ID: <script type="application/json">{"key": "value"}</script>
With None: <script type="application/json">{"key": "value"}</script>

```

### Step 42: `execute`

```
{}
```

**Result** (`execute`):

```
With ID: <script id="my_id" type="application/json">{"key": "value"}</script>

```

### Step 43: `execute`

```
{}
```

**Result** (`execute`):

```
Without arg: '<script type="application/json">{"key": "value"}</script>'

```

### Step 44: `execute`

```
{}
```

**Result** (`execute`):

```
Command failed (exit code 1):
Testing against Django installed in '/testbed/django' with up to 10 processes
Importing application utils_tests
Found 1 test(s).
Skipping setup of unused database(s): default, other.
System check identified no issues (0 silenced).
HtmlTests (unittest.loader._FailedTest.HtmlTests) ... ERROR

======================================================================
ERROR: HtmlTests (unittest.loader._FailedTest.HtmlTests)
----------------------------------------------------------------------
AttributeError: module 'utils_tests.test_html' has no attribute 'HtmlTests'

----------------------------------------------------------------------
Ran 1 test in 0.000s

FAILED (errors=1)

```

### Step 45: `execute`

```
{}
```

**Result** (`execute`):

```
Testing against Django installed in '/testbed/django' with up to 10 processes
Importing application utils_tests
Found 16 test(s).
Skipping setup of unused database(s): default, other.
System check identified no issues (0 silenced).
test_conditional_escape (utils_tests.test_html.TestUtilsHtml.test_conditional_escape) ... ok
test_escape (utils_tests.test_html.TestUtilsHtml.test_escape) ... ok
test_escapejs (utils_tests.test_html.TestUtilsHtml.test_escapejs) ... ok
test_format_html (utils_tests.test_html.TestUtilsHtml.test_format_html) ... ok
test_html_safe (utils_tests.test_html.TestUtilsHtml.test_html_safe) ... ok
test_html_safe_defines_html_error (utils_tests.test_html.TestUtilsHtml.test_html_safe_defines_html_error) ... ok
test_html_safe_doesnt_define_str (utils_tests.test_html.TestUtilsHtml.test_html_safe_doesnt_define_str) ... ok
test_html_safe_subclass (utils_tests.test_html.TestUtilsHtml.test_html_safe_subclass) ... ok
test_json_script (utils_tests.test_html.TestUtilsHtml.test_json_script) ... ok
test_linebreaks (utils_tests.test_html.TestUtilsHtml.test_linebreaks) ... ok
test_smart_urlquote (utils_tests.test_html.TestUtilsHtml.test_smart_urlquote) ... ok
test_strip_spaces_between_tags (utils_tests.test_html.TestUtilsHtml.test_strip_spaces_between_tags) ... ok
test_strip_tags (utils_tests.test_html.TestUtilsHtml.test_strip_tags) ... ok
test_strip_tags_files (utils_tests.test_html.TestUtilsHtml.test_strip_tags_files) ... ok
test_urlize (utils_tests.test_html.TestUtilsHtml.test_urlize) ... ok
test_urlize_unchanged_inputs (utils_tests.test_html.TestUtilsHtml.test_urlize_unchanged_inputs) ... ok

----------------------------------------------------------------------
Ran 16 tests in 0.136s

OK

```

### Step 46: `execute`

```
{}
```

**Result** (`execute`):

```
Testing against Django installed in '/testbed/django' with up to 10 processes
Importing application template_tests
Found 1 test(s).
Skipping setup of unused database(s): default, other.
System check identified no issues (0 silenced).
test_basic (template_tests.filter_tests.test_json_script.JsonScriptTests.test_basic) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.002s

OK

```

### Step 47: `execute`

```
{}
```

**Result** (`execute`):

```
With empty string: '<script type="application/json">{"key": "value"}</script>'
With 0: '<script type="application/json">{"key": "value"}</script>'

```

### Step 48: `execute`

```
{}
```

**Result** (`execute`):

```
test_escape (utils_tests.test_html.TestUtilsHtml.test_escape) ... ok
test_escapejs (utils_tests.test_html.TestUtilsHtml.test_escapejs) ... ok
test_format_html (utils_tests.test_html.TestUtilsHtml.test_format_html) ... ok
test_html_safe (utils_tests.test_html.TestUtilsHtml.test_html_safe) ... ok
test_html_safe_defines_html_error (utils_tests.test_html.TestUtilsHtml.test_html_safe_defines_html_error) ... ok
test_html_safe_doesnt_define_str (utils_tests.test_html.TestUtilsHtml.test_html_safe_doesnt_define_str) ... ok
test_html_safe_subclass (utils_tests.test_html.TestUtilsHtml.test_html_safe_subclass) ... ok
test_json_script (utils_tests.test_html.TestUtilsHtml.test_json_script) ... ok
test_linebreaks (utils_tests.test_html.TestUtilsHtml.test_linebreaks) ... ok
test_smart_urlquote (utils_tests.test_html.TestUtilsHtml.test_smart_urlquote) ... ok
test_strip_spaces_between_tags (utils_tests.test_html.TestUtilsHtml.test_strip_spaces_between_tags) ... ok
test_strip_tags (utils_tests.test_html.TestUtilsHtml.test_strip_tags) ... ok
test_strip_tags_files (utils_tests.test_html.TestUtilsHtml.test_strip_tags_files) ... ok
test_urlize (utils_tests.test_html.TestUtilsHtml.test_urlize) ... ok
test_urlize_unchanged_inputs (utils_tests.test_html.TestUtilsHtml.test_urlize_unchanged_inputs) ... ok

----------------------------------------------------------------------
Ran 17 tests in 0.161s

OK

```

## Patch

```diff
diff --git a/django/template/defaultfilters.py b/django/template/defaultfilters.py
index 5ccef38048..13070b303b 100644
--- a/django/template/defaultfilters.py
+++ b/django/template/defaultfilters.py
@@ -83,10 +83,10 @@ def escapejs_filter(value):
 
 
 @register.filter(is_safe=True)
-def json_script(value, element_id):
+def json_script(value, element_id=None):
     """
     Output value JSON-encoded, wrapped in a <script type="application/json">
-    tag.
+    tag (with an optional id).
     """
     return _json_script(value, element_id)
 
diff --git a/django/utils/html.py b/django/utils/html.py
index da1b5675ec..3536828f9b 100644
--- a/django/utils/html.py
+++ b/django/utils/html.py
@@ -61,7 +61,8 @@ _json_script_escapes = {
 }
 
 
-def json_script(value, element_id):
+
+def json_script(value, element_id=None):
     """
     Escape all the HTML/XML special characters with their unicode escapes, so
     value is safe to be output anywhere except for inside a tag attribute. Wrap
@@ -69,10 +70,14 @@ def json_script(value, element_id):
     """
     from django.core.serializers.json import DjangoJSONEncoder
     json_str = json.dumps(value, cls=DjangoJSONEncoder).translate(_json_script_escapes)
-    return format_html(
-        '<script id="{}" type="application/json">{}</script>',
-        element_id, mark_safe(json_str)
-    )
+    if element_id:
+        template = '<script id="{}" type="application/json">{}</script>'
+        args = (element_id, mark_safe(json_str))
+    else:
+        template = '<script type="application/json">{}</script>'
+        args = (mark_safe(json_str),)
+    return format_html(template, *args)
+
 
 
 def conditional_escape(text):
```