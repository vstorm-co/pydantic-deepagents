# django__django-11133

**Repository**: django/django
**Duration**: 603.3s
**Cost**: $0.0000
**Status**: Timed out
**Patch**: 22 lines

## Tool Calls

## Patch

```diff
diff --git a/django/http/response.py b/django/http/response.py
index 6a84e193ba..572f376ba9 100644
--- a/django/http/response.py
+++ b/django/http/response.py
@@ -229,7 +229,7 @@ class HttpResponseBase:
         # Handle string types -- we can't rely on force_bytes here because:
         # - Python attempts str conversion first
         # - when self._charset != 'utf-8' it re-encodes the content
-        if isinstance(value, bytes):
+        if isinstance(value, (bytes, memoryview)):
             return bytes(value)
         if isinstance(value, str):
             return bytes(value.encode(self.charset))
@@ -309,7 +309,7 @@ class HttpResponse(HttpResponseBase):
     @content.setter
     def content(self, value):
         # Consume iterators upon assignment to allow repeated iteration.
-        if hasattr(value, '__iter__') and not isinstance(value, (bytes, str)):
+        if hasattr(value, '__iter__') and not isinstance(value, (bytes, str, memoryview)):
             content = b''.join(self.make_bytes(chunk) for chunk in value)
             if hasattr(value, 'close'):
                 try:
```