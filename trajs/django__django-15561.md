# django__django-15561

**Repository**: django/django
**Duration**: 659.2s
**Cost**: $0.0000
**Status**: Timed out
**Patch**: 12 lines

## Tool Calls

## Patch

```diff
diff --git a/django/db/backends/base/schema.py b/django/db/backends/base/schema.py
index 9d6952df21..85d53e3b1a 100644
--- a/django/db/backends/base/schema.py
+++ b/django/db/backends/base/schema.py
@@ -1378,6 +1378,7 @@ class BaseDatabaseSchemaEditor:
         # - adding only a db_column and the column name is not changed
         non_database_attrs = [
             "blank",
+            "choices",
             "db_column",
             "editable",
             "error_messages",
```