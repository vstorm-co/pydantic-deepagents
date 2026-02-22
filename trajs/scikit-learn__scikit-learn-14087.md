# scikit-learn__scikit-learn-14087

**Repository**: scikit-learn/scikit-learn
**Duration**: 617.0s
**Cost**: $0.0000
**Status**: Timed out
**Patch**: 13 lines

## Tool Calls

## Patch

```diff
diff --git a/sklearn/linear_model/logistic.py b/sklearn/linear_model/logistic.py
index 1999f1dae..20603226b 100644
--- a/sklearn/linear_model/logistic.py
+++ b/sklearn/linear_model/logistic.py
@@ -2170,7 +2170,7 @@ class LogisticRegressionCV(LogisticRegression, BaseEstimator,
                 # Take the best scores across every fold and the average of
                 # all coefficients corresponding to the best scores.
                 best_indices = np.argmax(scores, axis=1)
-                if self.multi_class == 'ovr':
+                if multi_class == 'ovr':
                     w = np.mean([coefs_paths[i, best_indices[i], :]
                                  for i in range(len(folds))], axis=0)
                 else:
```