
import os
import json
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
import argopy
from argopy import DataFetcher
import warnings
warnings.filterwarnings('ignore')

app = Flask(__name__)

# Initialize database
def init_db():
    conn = sqlite3.connect('floatchat.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT,
            response TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# Enhanced query processor
class QueryProcessor:
    def __init__(self):
        self.keywords = {
            'temperature': ['temperature', 'temp', 'thermal', 'hot', 'cold'],
            'salinity': ['salinity', 'salt', 'psal'],
            'oxygen': ['oxygen', 'o2', 'doxy'],
            'location': ['mumbai', 'chennai', 'kerala', 'goa', 'indian ocean', 'bay of bengal', 'arabian sea'],
            'recent': ['recent', 'latest', 'last', 'current'],
            'profile': ['profile', 'depth', 'vertical'],
            'float': ['float', 'buoy', 'sensor']
        }

        # Adjusted regions with better float coverage
        self.regions = {
            'indian_ocean': [-20, 120, -40, 25],  # Broader Indian Ocean
            'bay_of_bengal': [85, 95, 10, 20],    # Central Bay of Bengal
            'arabian_sea': [60, 75, 10, 25],      # Central Arabian Sea
            'mumbai': [70, 75, 17, 22],           # Mumbai coast
            'chennai': [78, 85, 10, 15],          # Chennai coast
            'kerala': [74, 78, 8, 12],            # Kerala coast
            'global_test': [-180, 180, -60, 60]   # Global for testing
        }

    def parse_query(self, query):
        query_lower = query.lower()

        # Determine parameter
        param = 'TEMP'  # default
        if any(word in query_lower for word in self.keywords['salinity']):
            param = 'PSAL'
        elif any(word in query_lower for word in self.keywords['oxygen']):
            param = 'DOXY'

        # Determine region - start with global test for demo
        region = self.regions['global_test']  # default to global for better data availability
        region_name = 'Global Ocean'

        for location, coords in self.regions.items():
            if location.replace('_', ' ') in query_lower:
                region = coords
                region_name = location.replace('_', ' ').title()
                break

        # Use longer time period for better data availability
        end_date = datetime.now()
        start_date = end_date - timedelta(days=180)  # 6 months

        return {
            'parameter': param,
            'region': region,
            'region_name': region_name,
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d')
        }

# Enhanced data fetcher class
class ArgoDataFetcher:
    def __init__(self):
        self.processor = QueryProcessor()
        # Try different sources for better reliability
        try:
            argopy.set_options(mode='standard', src='erddap')
            self.src = 'erddap'
        except:
            try:
                argopy.set_options(mode='standard', src='argovis')
                self.src = 'argovis'
            except:
                argopy.set_options(mode='standard', src='gdac')
                self.src = 'gdac'

    def test_data_availability(self):
        """Test if we can fetch any ARGO data"""
        try:
            # Test with a small, reliable region
            test_region = [-10, 10, -10, 10, 0, 100, '2023-01-01', '2023-12-31']
            fetcher = DataFetcher()
            ds = fetcher.region(test_region).load()
            return True, f"Data source {self.src} is working"
        except Exception as e:
            return False, f"Data source {self.src} error: {str(e)}"

    def fetch_data(self, query_params):
        try:
            # Create region query with proper format
            region = query_params['region'] + [0, 500]  # Add depth range (0-500m)
            region.extend([query_params['start_date'], query_params['end_date']])

            print(f"Fetching data for region: {region}")

            # Try to fetch data
            fetcher = DataFetcher()

            # First try to load index to check availability
            try:
                index_data = fetcher.region(region).index
                if len(index_data) == 0:
                    return None, "No ARGO floats found in this region and time period"
                print(f"Found {len(index_data)} profiles in index")
            except Exception as e:
                return None, f"No data available in region: {str(e)}"

            # Now try to load actual data
            ds = fetcher.region(region).load().data

            if ds is None:
                return None, "No data could be loaded"

            # Check if dataset has profiles
            if hasattr(ds, 'N_PROF') and len(ds.N_PROF) == 0:
                return None, "Dataset loaded but contains no profiles"

            return ds, None

        except Exception as e:
            error_msg = str(e)
            if "zero-size array" in error_msg:
                return None, "No data found in the specified region. Try a broader area or different time period."
            elif "timeout" in error_msg.lower():
                return None, "Data server timeout. Please try again or use a smaller region."
            else:
                return None, f"Error fetching data: {error_msg}"

    def create_demo_data(self, param='TEMP'):
        """Create demo data when real data is unavailable"""
        depths = np.arange(0, 500, 25)
        if param == 'TEMP':
            values = 25 - (depths * 0.02) + np.random.normal(0, 0.5, len(depths))
            unit = '°C'
            param_name = 'Temperature'
        elif param == 'PSAL':
            values = 35 + np.random.normal(0, 0.2, len(depths))
            unit = 'PSU'
            param_name = 'Salinity'
        else:  # DOXY
            values = 250 - (depths * 0.3) + np.random.normal(0, 10, len(depths))
            unit = 'μmol/kg'
            param_name = 'Oxygen'

        return [{
            'pressure': depth,
            'value': value,
            'count': 1
        } for depth, value in zip(depths, values)], param_name, unit

    def process_query(self, user_query):
        try:
            # Parse the query
            query_params = self.processor.parse_query(user_query)

            # First test data availability
            available, status = self.test_data_availability()
            if not available:
                # Use demo data
                chart_data, param_name, unit = self.create_demo_data(query_params['parameter'])
                return {
                    'response': f"""Demo Mode: Showing sample {param_name.lower()} data for {query_params['region_name']}.

                    📊 Sample Data Statistics:
                    • Parameter: {param_name}
                    • Unit: {unit}
                    • Depth Range: 0-500m
                    • Sample Size: {len(chart_data)} measurements

                    ⚠️ Note: This is demonstration data. Real ARGO data unavailable due to: {status}

                    In production, this would show actual ARGO float measurements with:
                    • Real-time temperature, salinity, and oxygen profiles
                    • Precise geographical and temporal filtering
                    • Quality-controlled oceanographic data
                    """,
                    'data': {
                        'n_profiles': len(chart_data),
                        'parameter': query_params['parameter'],
                        'region': query_params['region_name'],
                        'demo_mode': True
                    },
                    'chart_data': chart_data
                }

            # Fetch real data
            dataset, error = self.fetch_data(query_params)

            if error:
                # Fallback to demo data
                chart_data, param_name, unit = self.create_demo_data(query_params['parameter'])
                return {
                    'response': f"""Unable to fetch live ARGO data: {error}

                    Showing demonstration data for {query_params['region_name']}:

                    📊 Demo {param_name} Profile:
                    • Depth Range: 0-500m
                    • Sample measurements: {len(chart_data)}
                    • Unit: {unit}

                    💡 This demonstrates the system's capability to process and visualize oceanographic profiles.
                    """,
                    'data': {
                        'n_profiles': len(chart_data),
                        'parameter': query_params['parameter'],
                        'region': query_params['region_name'],
                        'demo_mode': True
                    },
                    'chart_data': chart_data
                }

            # Process real data
            param = query_params['parameter']
            region_name = query_params['region_name']

            # Create summary statistics
            n_profiles = len(dataset.N_PROF) if hasattr(dataset, 'N_PROF') else 0

            if param in dataset.variables:
                param_data = dataset[param].values
                param_data = param_data[~np.isnan(param_data)] if len(param_data) > 0 else []

                if len(param_data) > 0:
                    mean_val = np.mean(param_data)
                    min_val = np.min(param_data)
                    max_val = np.max(param_data)

                    unit = '°C' if param == 'TEMP' else ('PSU' if param == 'PSAL' else 'μmol/kg')
                    param_name = 'Temperature' if param == 'TEMP' else ('Salinity' if param == 'PSAL' else 'Oxygen')

                    response = f"""Found {n_profiles} ARGO profiles in {region_name}.

                    📊 {param_name} Analysis:
                    • Average: {mean_val:.2f} {unit}
                    • Range: {min_val:.2f} - {max_val:.2f} {unit}
                    • Total measurements: {len(param_data)}

                    🌊 Data shows {param_name.lower()} variations across different depths and locations in the selected region.
                    """

                    # Prepare chart data
                    chart_data = self.prepare_chart_data(dataset, param)

                else:
                    response = f"Found {n_profiles} profiles but no valid {param} data in the selected region."
                    chart_data = None
            else:
                response = f"Parameter {param} not available in the dataset for {region_name}."
                chart_data = None

            return {
                'response': response,
                'data': {
                    'n_profiles': int(n_profiles),
                    'parameter': param,
                    'region': region_name,
                    'demo_mode': False
                },
                'chart_data': chart_data
            }

        except Exception as e:
            # Final fallback
            chart_data, param_name, unit = self.create_demo_data('TEMP')
            return {
                'response': f"""System Error: {str(e)}

                🔧 Showing demonstration data instead:

                📊 Sample Ocean Temperature Profile:
                • Demonstrates depth vs temperature relationship
                • Shows typical ocean stratification
                • Sample size: {len(chart_data)} points

                💡 This showcases the system's visualization capabilities.
                """,
                'data': {
                    'n_profiles': len(chart_data),
                    'parameter': 'TEMP',
                    'region': 'Demo Region',
                    'demo_mode': True
                },
                'chart_data': chart_data
            }

    def prepare_chart_data(self, dataset, param):
        try:
            if param not in dataset.variables:
                return None

            # Get data for plotting
            param_data = dataset[param].values
            pressure_data = dataset['PRES'].values if 'PRES' in dataset.variables else None

            if pressure_data is None:
                return None

            # Create depth profile data (average by pressure levels)
            pressure_bins = np.arange(0, 500, 25)
            binned_data = []

            for i in range(len(pressure_bins)-1):
                p_min, p_max = pressure_bins[i], pressure_bins[i+1]
                mask = (pressure_data >= p_min) & (pressure_data < p_max)

                if np.any(mask):
                    values = param_data[mask]
                    values = values[~np.isnan(values)]
                    if len(values) > 0:
                        binned_data.append({
                            'pressure': float((p_min + p_max) / 2),
                            'value': float(np.mean(values)),
                            'count': int(len(values))
                        })

            return binned_data

        except Exception as e:
            print(f"Error preparing chart data: {e}")
            return None

# Initialize components
init_db()
argo_fetcher = ArgoDataFetcher()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/query', methods=['POST'])
def process_query():
    try:
        data = request.get_json()
        user_query = data.get('query', '')

        if not user_query:
            return jsonify({'error': 'No query provided'}), 400

        # Process the query
        result = argo_fetcher.process_query(user_query)

        # Store in database
        conn = sqlite3.connect('floatchat.db')
        c = conn.cursor()
        c.execute('INSERT INTO queries (query, response) VALUES (?, ?)',
                  (user_query, result['response']))
        conn.commit()
        conn.close()

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/demo_queries')
def demo_queries():
    queries = [
        "Show me temperature data in Indian Ocean",
        "What is the salinity globally?",
        "Recent temperature profiles worldwide",
        "Show me oxygen levels in the ocean",
        "Temperature variation with depth"
    ]
    return jsonify(queries)

@app.route('/status')
def status():
    available, status = argo_fetcher.test_data_availability()
    return jsonify({
        'data_available': available,
        'status': status,
        'source': argo_fetcher.src
    })

if __name__ == '__main__':
    print("🌊 Starting FloatChat MVP...")
    print("📊 ARGO Data Integration: Ready")
    print("🤖 AI Query Processing: Active")
    print("🌍 Global Ocean Focus: Enabled")
    print("🔧 Demo Mode: Available for offline testing")
    print("\n🚀 Open http://localhost:5000 to start chatting with ocean data!")
    print("\n📈 Check /status endpoint to see data availability")
    app.run(debug=True, host='0.0.0.0', port=5000)
