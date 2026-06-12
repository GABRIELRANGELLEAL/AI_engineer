import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from datetime import datetime

# Read the CSV
df = pd.read_csv('test.csv')

# Convert date column to datetime
df['date'] = pd.to_datetime(df['date'])

# Basic statistics
print("=" * 80)
print("WEATHER DATA ANALYSIS REPORT")
print("=" * 80)
print("\n1. DATASET OVERVIEW")
print("-" * 80)
print(f"Total Records: {len(df)}")
print(f"Date Range: {df['date'].min().strftime('%Y-%m-%d')} to {df['date'].max().strftime('%Y-%m-%d')}")
print(f"Duration: {(df['date'].max() - df['date'].min()).days} days")
print(f"\nColumns: {', '.join(df.columns)}")

print("\n\n2. DESCRIPTIVE STATISTICS")
print("-" * 80)
print(df.describe().round(2))

print("\n\n3. MISSING VALUES")
print("-" * 80)
missing = df.isnull().sum()
print(missing)

print("\n\n4. KEY INSIGHTS")
print("-" * 80)
print(f"Average Temperature: {df['meantemp'].mean():.2f}°C")
print(f"Temperature Range: {df['meantemp'].min():.2f}°C to {df['meantemp'].max():.2f}°C")
print(f"Average Humidity: {df['humidity'].mean():.2f}%")
print(f"Average Wind Speed: {df['wind_speed'].mean():.2f} km/h")
print(f"Average Pressure: {df['meanpressure'].mean():.2f} hPa")

print(f"\nHottest Day: {df.loc[df['meantemp'].idxmax(), 'date'].strftime('%Y-%m-%d')} ({df['meantemp'].max():.2f}°C)")
print(f"Coldest Day: {df.loc[df['meantemp'].idxmin(), 'date'].strftime('%Y-%m-%d')} ({df['meantemp'].min():.2f}°C)")
print(f"Most Humid Day: {df.loc[df['humidity'].idxmax(), 'date'].strftime('%Y-%m-%d')} ({df['humidity'].max():.2f}%)")
print(f"Windiest Day: {df.loc[df['wind_speed'].idxmax(), 'date'].strftime('%Y-%m-%d')} ({df['wind_speed'].max():.2f} km/h)")

# Monthly analysis
df['month'] = df['date'].dt.month
df['month_name'] = df['date'].dt.strftime('%B')
monthly_stats = df.groupby('month_name').agg({
    'meantemp': 'mean',
    'humidity': 'mean',
    'wind_speed': 'mean',
    'meanpressure': 'mean'
}).round(2)

print("\n\n5. MONTHLY AVERAGES")
print("-" * 80)
print(monthly_stats)

# Correlations
print("\n\n6. CORRELATION MATRIX")
print("-" * 80)
corr_matrix = df[['meantemp', 'humidity', 'wind_speed', 'meanpressure']].corr()
print(corr_matrix.round(3))

# Create visualizations
plt.style.use('seaborn-v0_8-darkgrid')
fig = plt.figure(figsize=(16, 12))

# 1. Temperature over time
ax1 = plt.subplot(3, 3, 1)
plt.plot(df['date'], df['meantemp'], color='#FF6B6B', linewidth=1.5)
plt.title('Temperature Over Time', fontsize=12, fontweight='bold')
plt.xlabel('Date')
plt.ylabel('Temperature (°C)')
plt.xticks(rotation=45)
plt.grid(True, alpha=0.3)

# 2. Humidity over time
ax2 = plt.subplot(3, 3, 2)
plt.plot(df['date'], df['humidity'], color='#4ECDC4', linewidth=1.5)
plt.title('Humidity Over Time', fontsize=12, fontweight='bold')
plt.xlabel('Date')
plt.ylabel('Humidity (%)')
plt.xticks(rotation=45)
plt.grid(True, alpha=0.3)

# 3. Wind Speed over time
ax3 = plt.subplot(3, 3, 3)
plt.plot(df['date'], df['wind_speed'], color='#95E1D3', linewidth=1.5)
plt.title('Wind Speed Over Time', fontsize=12, fontweight='bold')
plt.xlabel('Date')
plt.ylabel('Wind Speed (km/h)')
plt.xticks(rotation=45)
plt.grid(True, alpha=0.3)

# 4. Temperature distribution
ax4 = plt.subplot(3, 3, 4)
plt.hist(df['meantemp'], bins=30, color='#FF6B6B', alpha=0.7, edgecolor='black')
plt.title('Temperature Distribution', fontsize=12, fontweight='bold')
plt.xlabel('Temperature (°C)')
plt.ylabel('Frequency')
plt.grid(True, alpha=0.3)

# 5. Humidity distribution
ax5 = plt.subplot(3, 3, 5)
plt.hist(df['humidity'], bins=30, color='#4ECDC4', alpha=0.7, edgecolor='black')
plt.title('Humidity Distribution', fontsize=12, fontweight='bold')
plt.xlabel('Humidity (%)')
plt.ylabel('Frequency')
plt.grid(True, alpha=0.3)

# 6. Wind Speed distribution
ax6 = plt.subplot(3, 3, 6)
plt.hist(df['wind_speed'], bins=30, color='#95E1D3', alpha=0.7, edgecolor='black')
plt.title('Wind Speed Distribution', fontsize=12, fontweight='bold')
plt.xlabel('Wind Speed (km/h)')
plt.ylabel('Frequency')
plt.grid(True, alpha=0.3)

# 7. Correlation heatmap
ax7 = plt.subplot(3, 3, 7)
sns.heatmap(corr_matrix, annot=True, cmap='coolwarm', center=0, 
            square=True, linewidths=1, cbar_kws={"shrink": 0.8}, fmt='.2f')
plt.title('Correlation Heatmap', fontsize=12, fontweight='bold')

# 8. Monthly average temperature
ax8 = plt.subplot(3, 3, 8)
month_order = ['January', 'February', 'March', 'April']
monthly_temp = df.groupby('month_name')['meantemp'].mean().reindex(month_order)
colors = plt.cm.RdYlBu_r(np.linspace(0.3, 0.9, len(monthly_temp)))
plt.bar(range(len(monthly_temp)), monthly_temp.values, color=colors, edgecolor='black')
plt.xticks(range(len(monthly_temp)), monthly_temp.index, rotation=45)
plt.title('Average Temperature by Month', fontsize=12, fontweight='bold')
plt.ylabel('Temperature (°C)')
plt.grid(True, alpha=0.3, axis='y')

# 9. Scatter: Temperature vs Humidity
ax9 = plt.subplot(3, 3, 9)
plt.scatter(df['meantemp'], df['humidity'], alpha=0.5, c=df['wind_speed'], 
            cmap='viridis', s=50, edgecolors='black', linewidth=0.5)
plt.colorbar(label='Wind Speed (km/h)')
plt.title('Temperature vs Humidity', fontsize=12, fontweight='bold')
plt.xlabel('Temperature (°C)')
plt.ylabel('Humidity (%)')
plt.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('weather_analysis.png', dpi=300, bbox_inches='tight')
print("\n\n✓ Visualizations saved as 'weather_analysis.png'")

# Create additional time series plot
fig2, axes = plt.subplots(4, 1, figsize=(14, 10))

axes[0].plot(df['date'], df['meantemp'], color='#FF6B6B', linewidth=2)
axes[0].set_title('Temperature Trends', fontsize=14, fontweight='bold')
axes[0].set_ylabel('Temperature (°C)', fontsize=10)
axes[0].grid(True, alpha=0.3)
axes[0].fill_between(df['date'], df['meantemp'], alpha=0.3, color='#FF6B6B')

axes[1].plot(df['date'], df['humidity'], color='#4ECDC4', linewidth=2)
axes[1].set_title('Humidity Trends', fontsize=14, fontweight='bold')
axes[1].set_ylabel('Humidity (%)', fontsize=10)
axes[1].grid(True, alpha=0.3)
axes[1].fill_between(df['date'], df['humidity'], alpha=0.3, color='#4ECDC4')

axes[2].plot(df['date'], df['wind_speed'], color='#95E1D3', linewidth=2)
axes[2].set_title('Wind Speed Trends', fontsize=14, fontweight='bold')
axes[2].set_ylabel('Wind Speed (km/h)', fontsize=10)
axes[2].grid(True, alpha=0.3)
axes[2].fill_between(df['date'], df['wind_speed'], alpha=0.3, color='#95E1D3')

axes[3].plot(df['date'], df['meanpressure'], color='#A8E6CF', linewidth=2)
axes[3].set_title('Pressure Trends', fontsize=14, fontweight='bold')
axes[3].set_ylabel('Pressure (hPa)', fontsize=10)
axes[3].set_xlabel('Date', fontsize=10)
axes[3].grid(True, alpha=0.3)
axes[3].fill_between(df['date'], df['meanpressure'], alpha=0.3, color='#A8E6CF')

for ax in axes:
    ax.tick_params(axis='x', rotation=45)

plt.tight_layout()
plt.savefig('weather_trends.png', dpi=300, bbox_inches='tight')
print("✓ Time series visualizations saved as 'weather_trends.png'")

print("\n" + "=" * 80)
print("ANALYSIS COMPLETE!")
print("=" * 80)
