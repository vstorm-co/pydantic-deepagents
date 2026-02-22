# django__django-13212

**Repository**: django/django
**Duration**: 603.1s
**Cost**: $0.0000
**Status**: Timed out
**Patch**: 179 lines

## Tool Calls

## Patch

```diff
diff --git a/django/core/validators.py b/django/core/validators.py
index 84b4f31ec7..3710736f44 100644
--- a/django/core/validators.py
+++ b/django/core/validators.py
@@ -48,7 +48,7 @@ class RegexValidator:
         regex_matches = self.regex.search(str(value))
         invalid_input = regex_matches if self.inverse_match else not regex_matches
         if invalid_input:
-            raise ValidationError(self.message, code=self.code)
+            raise ValidationError(self.message, code=self.code, params={'value': value})
 
     def __eq__(self, other):
         return (
@@ -100,11 +100,11 @@ class URLValidator(RegexValidator):
 
     def __call__(self, value):
         if not isinstance(value, str):
-            raise ValidationError(self.message, code=self.code)
+            raise ValidationError(self.message, code=self.code, params={'value': value})
         # Check if the scheme is valid.
         scheme = value.split('://')[0].lower()
         if scheme not in self.schemes:
-            raise ValidationError(self.message, code=self.code)
+            raise ValidationError(self.message, code=self.code, params={'value': value})
 
         # Then check full URL
         try:
@@ -115,7 +115,7 @@ class URLValidator(RegexValidator):
                 try:
                     scheme, netloc, path, query, fragment = urlsplit(value)
                 except ValueError:  # for example, "Invalid IPv6 URL"
-                    raise ValidationError(self.message, code=self.code)
+                    raise ValidationError(self.message, code=self.code, params={'value': value})
                 try:
                     netloc = punycode(netloc)  # IDN -> ACE
                 except UnicodeError:  # invalid domain part
@@ -132,14 +132,14 @@ class URLValidator(RegexValidator):
                 try:
                     validate_ipv6_address(potential_ip)
                 except ValidationError:
-                    raise ValidationError(self.message, code=self.code)
+                    raise ValidationError(self.message, code=self.code, params={'value': value})
 
         # The maximum length of a full host name is 253 characters per RFC 1034
         # section 3.1. It's defined to be 255 bytes or less, but this includes
         # one byte for the length of the name and one byte for the trailing dot
         # that's used to indicate absolute names in DNS.
         if len(urlsplit(value).netloc) > 253:
-            raise ValidationError(self.message, code=self.code)
+            raise ValidationError(self.message, code=self.code, params={'value': value})
 
 
 integer_validator = RegexValidator(
@@ -208,12 +208,12 @@ class EmailValidator:
 
     def __call__(self, value):
         if not value or '@' not in value:
-            raise ValidationError(self.message, code=self.code)
+            raise ValidationError(self.message, code=self.code, params={'value': value})
 
         user_part, domain_part = value.rsplit('@', 1)
 
         if not self.user_regex.match(user_part):
-            raise ValidationError(self.message, code=self.code)
+            raise ValidationError(self.message, code=self.code, params={'value': value})
 
         if (domain_part not in self.domain_allowlist and
                 not self.validate_domain_part(domain_part)):
@@ -225,7 +225,7 @@ class EmailValidator:
             else:
                 if self.validate_domain_part(domain_part):
                     return
-            raise ValidationError(self.message, code=self.code)
+            raise ValidationError(self.message, code=self.code, params={'value': value})
 
     def validate_domain_part(self, domain_part):
         if self.domain_regex.match(domain_part):
@@ -256,14 +256,14 @@ slug_re = _lazy_re_compile(r'^[-a-zA-Z0-9_]+\Z')
 validate_slug = RegexValidator(
     slug_re,
     # Translators: "letters" means latin letters: a-z and A-Z.
-    _('Enter a valid “slug” consisting of letters, numbers, underscores or hyphens.'),
+    _('Enter a valid "slug" consisting of letters, numbers, underscores or hyphens.'),
     'invalid'
 )
 
 slug_unicode_re = _lazy_re_compile(r'^[-\w]+\Z')
 validate_unicode_slug = RegexValidator(
     slug_unicode_re,
-    _('Enter a valid “slug” consisting of Unicode letters, numbers, underscores, or hyphens.'),
+    _('Enter a valid "slug" consisting of Unicode letters, numbers, underscores, or hyphens.'),
     'invalid'
 )
 
@@ -272,12 +272,12 @@ def validate_ipv4_address(value):
     try:
         ipaddress.IPv4Address(value)
     except ValueError:
-        raise ValidationError(_('Enter a valid IPv4 address.'), code='invalid')
+        raise ValidationError(_('Enter a valid IPv4 address.'), code='invalid', params={'value': value})
 
 
 def validate_ipv6_address(value):
     if not is_valid_ipv6_address(value):
-        raise ValidationError(_('Enter a valid IPv6 address.'), code='invalid')
+        raise ValidationError(_('Enter a valid IPv6 address.'), code='invalid', params={'value': value})
 
 
 def validate_ipv46_address(value):
@@ -287,7 +287,7 @@ def validate_ipv46_address(value):
         try:
             validate_ipv6_address(value)
         except ValidationError:
-            raise ValidationError(_('Enter a valid IPv4 or IPv6 address.'), code='invalid')
+            raise ValidationError(_('Enter a valid IPv4 or IPv6 address.'), code='invalid', params={'value': value})
 
 
 ip_address_validator_map = {
@@ -438,7 +438,7 @@ class DecimalValidator:
     def __call__(self, value):
         digit_tuple, exponent = value.as_tuple()[1:]
         if exponent in {'F', 'n', 'N'}:
-            raise ValidationError(self.messages['invalid'])
+            raise ValidationError(self.messages['invalid'], code='invalid', params={'value': value})
         if exponent >= 0:
             # A positive exponent adds that many trailing zeros.
             digits = len(digit_tuple) + exponent
@@ -460,20 +460,20 @@ class DecimalValidator:
             raise ValidationError(
                 self.messages['max_digits'],
                 code='max_digits',
-                params={'max': self.max_digits},
+                params={'max': self.max_digits, 'value': value},
             )
         if self.decimal_places is not None and decimals > self.decimal_places:
             raise ValidationError(
                 self.messages['max_decimal_places'],
                 code='max_decimal_places',
-                params={'max': self.decimal_places},
+                params={'max': self.decimal_places, 'value': value},
             )
         if (self.max_digits is not None and self.decimal_places is not None and
                 whole_digits > (self.max_digits - self.decimal_places)):
             raise ValidationError(
                 self.messages['max_whole_digits'],
                 code='max_whole_digits',
-                params={'max': (self.max_digits - self.decimal_places)},
+                params={'max': (self.max_digits - self.decimal_places), 'value': value},
             )
 
     def __eq__(self, other):
@@ -487,7 +487,7 @@ class DecimalValidator:
 @deconstructible
 class FileExtensionValidator:
     message = _(
-        'File extension “%(extension)s” is not allowed. '
+        'File extension "%(extension)s" is not allowed. '
         'Allowed extensions are: %(allowed_extensions)s.'
     )
     code = 'invalid_extension'
@@ -509,7 +509,8 @@ class FileExtensionValidator:
                 code=self.code,
                 params={
                     'extension': extension,
-                    'allowed_extensions': ', '.join(self.allowed_extensions)
+                    'allowed_extensions': ', '.join(self.allowed_extensions),
+                    'value': value,
                 }
             )
 
@@ -550,7 +551,7 @@ class ProhibitNullCharactersValidator:
 
     def __call__(self, value):
         if '\x00' in str(value):
-            raise ValidationError(self.message, code=self.code)
+            raise ValidationError(self.message, code=self.code, params={'value': value})
 
     def __eq__(self, other):
         return (
```