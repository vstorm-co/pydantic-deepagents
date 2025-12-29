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

### Visualization with Matplotlib

Always save charts to `/workspace/` directory so they can be viewed in the app.

```python
import matplotlib.pyplot as plt
import seaborn as sns

# Set style for better looking charts
plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")
```

#### Bar Chart
```python
plt.figure(figsize=(10, 6))
df.groupby('category')['value'].sum().plot(kind='bar', color='steelblue', edgecolor='black')
plt.title('Value by Category', fontsize=14, fontweight='bold')
plt.xlabel('Category')
plt.ylabel('Total Value')
plt.xticks(rotation=45, ha='right')
plt.tight_layout()
plt.savefig('/workspace/bar_chart.png', dpi=150, bbox_inches='tight')
plt.close()
```

#### Line Chart (Time Series)
```python
plt.figure(figsize=(12, 6))
plt.plot(df['date'], df['value'], marker='o', linewidth=2, markersize=4)
plt.title('Value Over Time', fontsize=14, fontweight='bold')
plt.xlabel('Date')
plt.ylabel('Value')
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig('/workspace/line_chart.png', dpi=150, bbox_inches='tight')
plt.close()
```

#### Pie Chart
```python
plt.figure(figsize=(8, 8))
data = df.groupby('category')['value'].sum()
plt.pie(data, labels=data.index, autopct='%1.1f%%', startangle=90,
        colors=sns.color_palette('pastel'))
plt.title('Distribution by Category', fontsize=14, fontweight='bold')
plt.tight_layout()
plt.savefig('/workspace/pie_chart.png', dpi=150, bbox_inches='tight')
plt.close()
```

#### Histogram
```python
plt.figure(figsize=(10, 6))
plt.hist(df['value'], bins=20, color='steelblue', edgecolor='black', alpha=0.7)
plt.title('Value Distribution', fontsize=14, fontweight='bold')
plt.xlabel('Value')
plt.ylabel('Frequency')
plt.axvline(df['value'].mean(), color='red', linestyle='--', label=f'Mean: {df["value"].mean():.2f}')
plt.legend()
plt.tight_layout()
plt.savefig('/workspace/histogram.png', dpi=150, bbox_inches='tight')
plt.close()
```

#### Scatter Plot
```python
plt.figure(figsize=(10, 6))
plt.scatter(df['x'], df['y'], alpha=0.6, c=df['category'].astype('category').cat.codes, cmap='viridis')
plt.title('X vs Y Relationship', fontsize=14, fontweight='bold')
plt.xlabel('X')
plt.ylabel('Y')
plt.colorbar(label='Category')
plt.tight_layout()
plt.savefig('/workspace/scatter.png', dpi=150, bbox_inches='tight')
plt.close()
```

#### Heatmap (Correlation Matrix)
```python
plt.figure(figsize=(10, 8))
correlation = df.select_dtypes(include='number').corr()
sns.heatmap(correlation, annot=True, cmap='coolwarm', center=0,
            fmt='.2f', square=True, linewidths=0.5)
plt.title('Correlation Matrix', fontsize=14, fontweight='bold')
plt.tight_layout()
plt.savefig('/workspace/heatmap.png', dpi=150, bbox_inches='tight')
plt.close()
```

#### Multiple Subplots
```python
fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# Plot 1: Bar chart
df.groupby('category')['value'].sum().plot(kind='bar', ax=axes[0, 0], color='steelblue')
axes[0, 0].set_title('Total by Category')
axes[0, 0].tick_params(axis='x', rotation=45)

# Plot 2: Line chart
df.groupby('date')['value'].mean().plot(ax=axes[0, 1], marker='o')
axes[0, 1].set_title('Average Over Time')

# Plot 3: Histogram
axes[1, 0].hist(df['value'], bins=15, color='green', alpha=0.7)
axes[1, 0].set_title('Value Distribution')

# Plot 4: Box plot
df.boxplot(column='value', by='category', ax=axes[1, 1])
axes[1, 1].set_title('Value by Category')
plt.suptitle('')  # Remove auto-generated title

plt.tight_layout()
plt.savefig('/workspace/dashboard.png', dpi=150, bbox_inches='tight')
plt.close()
```

### Interactive HTML Charts (Plotly)

For interactive charts that can be viewed in the browser:

```python
import plotly.express as px
import plotly.graph_objects as go

# Interactive bar chart
fig = px.bar(df, x='category', y='value', color='category',
             title='Value by Category')
fig.write_html('/workspace/interactive_bar.html')

# Interactive line chart
fig = px.line(df, x='date', y='value', title='Value Over Time',
              markers=True)
fig.write_html('/workspace/interactive_line.html')

# Interactive scatter with hover
fig = px.scatter(df, x='x', y='y', color='category', size='value',
                 hover_data=['name'], title='Interactive Scatter')
fig.write_html('/workspace/interactive_scatter.html')

# Interactive pie chart
fig = px.pie(df, values='value', names='category', title='Distribution')
fig.write_html('/workspace/interactive_pie.html')
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
