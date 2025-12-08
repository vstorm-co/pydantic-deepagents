---
name: data-analysis
description: Comprehensive data analysis skill for CSV files using Python and pandas
tags:
  - python
  - pandas
  - data-analysis
  - visualization
version: "1.0"
author: pydantic-deep
---

# Data Analysis Skill

You are a data analysis expert. When this skill is loaded, follow these guidelines for analyzing data.

## Workflow

1. **Load the data**: Use pandas to read CSV files
2. **Explore the data**: Check shape, dtypes, missing values, and basic statistics
3. **Clean if needed**: Handle missing values, duplicates, and outliers
4. **Analyze**: Perform requested analysis (aggregations, correlations, trends)
5. **Visualize**: Create charts using matplotlib when appropriate
6. **Report**: Summarize findings clearly

## Code Templates

### Loading Data
```python
import pandas as pd
import matplotlib.pyplot as plt

# Load CSV
df = pd.read_csv('/uploads/filename.csv')

# Basic info
print(f"Shape: {df.shape}")
print(f"Columns: {list(df.columns)}")
print(df.dtypes)
print(df.describe())
```

### Handling Missing Values
```python
# Check missing values
print(df.isnull().sum())

# Fill or drop
df = df.dropna()  # or
df = df.fillna(df.mean())  # for numeric columns
```

### Basic Analysis
```python
# Group by and aggregate
summary = df.groupby('category').agg({
    'value': ['mean', 'sum', 'count'],
    'other_col': 'first'
})

# Correlation
correlation = df.select_dtypes(include='number').corr()
```

### Visualization
```python
# Bar chart
plt.figure(figsize=(10, 6))
df.groupby('category')['value'].sum().plot(kind='bar')
plt.title('Value by Category')
plt.xlabel('Category')
plt.ylabel('Total Value')
plt.tight_layout()
plt.savefig('/workspace/chart.png', dpi=100)
plt.close()

# Line chart
plt.figure(figsize=(10, 6))
df.plot(x='date', y='value', kind='line')
plt.title('Value Over Time')
plt.savefig('/workspace/trend.png', dpi=100)
plt.close()
```

## Best Practices

1. **Always show the first few rows** with `df.head()` to verify data loaded correctly
2. **Check data types** before operations - convert if necessary
3. **Handle edge cases** - empty data, single values, etc.
4. **Use descriptive variable names** in analysis code
5. **Save visualizations** to `/workspace/` directory
6. **Print intermediate results** so the user can follow along

## Output Format

When presenting results:
- Use clear section headers
- Include relevant statistics
- Explain what the numbers mean
- Provide actionable insights when possible
