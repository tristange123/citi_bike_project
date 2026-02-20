# 🚲 Citi Bike Availability Predictor

A machine learning web application that predicts Citi Bike station demand in NYC by integrating historical ride data with real-time weather forecasts.


---

## Project Overview
As the popularity of NYC's **Citi Bike** ride share continues to increases, the lack of availables bikes and docks in the city's busiest neighborhood is becoming 
a growing issue.
This project live forecasts bike and dock availability for coming week. The model uses **XGBoost** create predictions based on past data, then updates those predications based on current station capacities. It features data pipelines for fetching, cleaning, and aggregating data from the following data sources: a historically collected time series dataset for station capacities, current bike data from Citi Bike's official API, historical weather API data from Meteostat, and live forecasts Open-Meteo.


## Datasets
* **Historic Station Data:** https://www.kaggle.com/datasets/rosenthal/citi-bike-stations
Because historic Citi Bike capacity data is not kept by Citi-Bike official api, capacity datasets must be manually created from repeated API pulls.
This Kaggle Dataset was the best of these such datasets I could find, containing all system data from 2016 to 2021, collected in 2 minutes intervals, split into 50 seperate csv files. However much of the data is either incorrectly labeled or incomplete. The file **data_processing.py** cleans, filters, and aggregates these files into one workable csv. I chose to use only data from 2017 to 2019 for my dataset, ommiting 2020 and 2021 due to the pandemic and 2016 since the system was still in this early stages. I also chose to only predict for stations in Manhattan below 14th. This area of the Citi-Bike System was already very well developed in 2017, thus data from 2017-2019 was generalize more cleanly to the present.

* **Legacy Station Information:** Located in citibike-stations.csv
Pulled from a public repo (I forgot where). Citi Bike changed their API and ID system and some point. Thus this dataset had to be used to align historic and current data together.

* **Individual Station Infomation:** https://gbfs.citibikenyc.com/gbfs/en/station_status.json
* **Live Station Data:** https://gbfs.citibikenyc.com/gbfs/en/station_information.json
* **Historic Weather Data:** Meteostat API
* **Live Weather Forecasts:** Open-Meteo API


## Key Features
* **Smart Weather Integration:** Uses historical weather data from 2017-2019 and live 7-day forecasts.
* **Advanced Feature Engineering:** Includes integration for Holidays and Working Days, and advanced weather features such as 'time_since_rain' and 'time_since_dry' impact.
* **Bayesian Style Live Updating:** Shifts model prediction mean with current station data to account for error. Includes a decay function to decrease updating impact with respect to time.
* **Interactive Dashboard Deployment:** Built with **Streamlit** for easy visualization for predicted trends and forecasts.

## Technologies Used
* **Language:** Python 3.11+
* **ML Model:** XGBoost (Gradient Boosting with CatBoost)
* **Data Handling:** Pandas, NumPy
* **APIs:** Meteostat (Historical), Open-Meteo (Forecast)
* **Frontend:** Streamlit
* **Environment:** Conda

## 🚀 Getting Started

### 1. Clone the Repository
```bash
git clone [https://github.com/yourusername/citi-bike-predictor.git](https://github.com/yourusername/citi-bike-predictor.git)
cd citi-bike-predictor