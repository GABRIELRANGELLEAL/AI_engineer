import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Read the CSV file
df = pd.read_csv('test.csv')
df['date'] = pd.to_datetime(df['date'])

# Create a figure with subplots
fig, axes = plt.subplots(2, 2, figsize=(15, 10))
fig.suptitle('Weather Data Analysis (January - April 2017)', fontsize=16, fontweight='bold')

# Plot 1: Temperature over time
axes[0, 0].plot(df['date'], df['meantemp'], color='#FF6B6B', linewidth=2)
axes[0, 0].set_title('Mean Temperature', fontsize=12, fontweight='bold')
axes[0, 0].set_ylabel('Temperature (°C)', fontsize=10)
axes[0, 0].grid(True, alpha=0.3)
axes[0, 0].xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))

# Plot 2: Humidity over time
axes[0, 1].plot(df['date'], df['humidity'], color='#4ECDC4', linewidth=2)
axes[0, 1].set_title('Humidity', fontsize=12, fontweight='bold')
axes[0, 1].set_ylabel('Humidity (%)', fontsize=10)
axes[0, 1].grid(True, alpha=0.3)
axes[0, 1].xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))

# Plot 3: Wind Speed over time
axes[1, 0].plot(df['date'], df['wind_speed'], color='#95E1D3', linewidth=2)
axes[1, 0].set_title('Wind Speed', fontsize=12, fontweight='bold')
axes[1, 0].set_ylabel('Wind Speed (m/s)', fontsize=10)
axes[1, 0].set_xlabel('Date', fontsize=10)
axes[1, 0].grid(True, alpha=0.3)
axes[1, 0].xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))

# Plot 4: Mean Pressure over time
axes[1, 1].plot(df['date'], df['meanpressure'], color='#A8E6CF', linewidth=2)
axes[1, 1].set_title('Mean Pressure', fontsize=12, fontweight='bold')
axes[1, 1].set_ylabel('Pressure (hPa)', fontsize=10)
axes[1, 1].set_xlabel('Date', fontsize=10)
axes[1, 1].grid(True, alpha=0.3)
axes[1, 1].xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))

# Rotate x-axis labels for better readability
for ax in axes.flat:
    ax.tick_params(axis='x', rotation=45)

plt.tight_layout()
plt.savefig('weather_graph.png', dpi=300, bbox_inches='tight')
print("Graph saved as 'weather_graph.png'")

# Create a bonus correlation plot
fig2, ax = plt.subplots(figsize=(10, 8))
scatter = ax.scatter(df['meantemp'], df['humidity'], 
                     c=df['wind_speed'], cmap='viridis', 
                     s=100, alpha=0.6, edgecolors='black', linewidth=0.5)
ax.set_xlabel('Mean Temperature (°C)', fontsize=12)
ax.set_ylabel('Humidity (%)', fontsize=12)
ax.set_title('Temperature vs Humidity (colored by Wind Speed)', fontsize=14, fontweight='bold')
ax.grid(True, alpha=0.3)
cbar = plt.colorbar(scatter, ax=ax)
cbar.set_label('Wind Speed (m/s)', fontsize=10)

plt.tight_layout()
plt.savefig('weather_correlation.png', dpi=300, bbox_inches='tight')
print("Correlation graph saved as 'weather_correlation.png'")
