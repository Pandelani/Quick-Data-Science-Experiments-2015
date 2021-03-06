import pandas as pd
import numpy as np
from sklearn.cross_validation import train_test_split
import operator
from sklearn.ensemble import RandomForestRegressor
import cPickle as pickle


def rmspe(y, yhat):
    return np.sqrt(np.mean((yhat/y-1) ** 2))

def rmspe_xg(yhat, y):
    y = np.expm1(y.get_label())
    yhat = np.expm1(yhat)
    return "rmspe", rmspe(y,yhat)

def build_features(features, data):
    # remove NaNs
    data.fillna(0, inplace=True)
    data.loc[data.Open.isnull(), 'Open'] = 1
    # Use some properties directly
    features.extend(['Store', 'CompetitionDistance', 'Promo', 'Promo2', 'SchoolHoliday'])

    # Label encode some features
    features.extend(['StoreType', 'Assortment', 'StateHoliday'])
    mappings = {'0':0, 'a':1, 'b':2, 'c':3, 'd':4}
    data.StoreType.replace(mappings, inplace=True)
    data.Assortment.replace(mappings, inplace=True)
    data.StateHoliday.replace(mappings, inplace=True)

    features.extend(['DayOfWeek', 'Month', 'Day', 'Year', 'WeekOfYear'])
    data['Year'] = data.Date.dt.year
    data['Month'] = data.Date.dt.month
    data['Day'] = data.Date.dt.day
    data['DayOfWeek'] = data.Date.dt.dayofweek
    data['WeekOfYear'] = data.Date.dt.weekofyear

    features.append('CompetitionOpen')
    data['CompetitionOpen'] = 12 * (data.Year - data.CompetitionOpenSinceYear) + \
        (data.Month - data.CompetitionOpenSinceMonth)
    # Promo open time in months
    features.append('PromoOpen')
    data['PromoOpen'] = 12 * (data.Year - data.Promo2SinceYear) + \
        (data.WeekOfYear - data.Promo2SinceWeek) / 4.0
    data['PromoOpen'] = data.PromoOpen.apply(lambda x: x if x > 0 else 0)
    data.loc[data.Promo2SinceYear == 0, 'PromoOpen'] = 0

    # Indicate that sales on that day are in promo interval
    features.extend(['IsPromoMonth', 'IsPromoNextMonth', 'IsPromoLastMonth'])
    month2str = {1:'Jan', 2:'Feb', 3:'Mar', 4:'Apr', 5:'May', 6:'Jun', \
             7:'Jul', 8:'Aug', 9:'Sept', 10:'Oct', 11:'Nov', 12:'Dec'}
    data['monthStr'] = data.Month.map(month2str)
    data['nextMonthStr'] = data.Month.apply(lambda x: x + 1).map(month2str)
    data['lastMonthStr'] = data.Month.apply(lambda x: x - 1).map(month2str)
    
    data.loc[data.PromoInterval == 0, 'PromoInterval'] = ''
    data['IsPromoMonth'] = 0
    data['IsPromoNextMonth'] = 0
    data['IsPromoLastMonth'] = 0
    
    for interval in data.PromoInterval.unique():
        if interval != '':
            for month in interval.split(','):
                data.loc[(data.monthStr == month) & (data.PromoInterval == interval), 'IsPromoMonth'] = 1
                data.loc[(data.nextMonthStr == month) & (data.PromoInterval == interval), 'IsPromoNextMonth'] = 1
                data.loc[(data.lastMonthStr == month) & (data.PromoInterval == interval), 'IsPromoLastMonth'] = 1

    return data


## Start of main script
print("Load the training, test and store data using pandas")
features = []
types = {'CompetitionOpenSinceYear': np.dtype(int),
         'CompetitionOpenSinceMonth': np.dtype(int),
         'StateHoliday': np.dtype(str),
         'Promo2SinceWeek': np.dtype(int),
         'SchoolHoliday': np.dtype(float),
         'PromoInterval': np.dtype(str)}
train = pd.read_csv("../data/train.csv", parse_dates=[2], dtype=types)
test = pd.read_csv("../data/test.csv", parse_dates=[3], dtype=types)
store = pd.read_csv("../data/store_features.pd")
for feature in store.columns:
    if '_' in feature:
        features += [feature]

print("Assume store open, if not provided")
train.fillna(1, inplace=True)
test.fillna(1, inplace=True)

print("Consider only open stores for training. Closed stores wont count into the score.")
train = train[train["Open"] != 0]
print("Use only Sales bigger then zero. Simplifies calculation of rmspe")
train = train[train["Sales"] > 0]

print("Join with store")
train = pd.merge(train, store, on='Store')
test = pd.merge(test, store, on='Store')

print("augment features")
build_features(features, train)
build_features([], test)
print(features)

X_valid = train[train.Date >= '2015-06-15']
X_train = train[train.Date < '2015-06-15']
print X_train.shape, X_valid.shape
y_train = np.log1p(X_train.Sales)
y_valid = np.log1p(X_valid.Sales)

######### load models and validation predictions
modelResults = {}
# load xgb stuff
print "loading xgb"
yhat = pickle.load(open("../data/xgb_valid"))
modelResults['xgb'] = yhat
# load sklearn tf stuff 
print "loading rf"
yhat = pickle.load(open("../data/rf_valid"))
modelResults['rf'] = yhat
# load sklearn extratree stff
print "loading extratree"
yhat = pickle.load(open("../data/et_valid"))
modelResults['et'] = yhat

######### adjust weights
results = {}
xgb_weights, rf_weights, et_weights = [], [], []
step = 0.01
for i in range(int(1/step)):
    xgb_weight = i * step
    for j in range(int(1/step)):
        rf_weight = j * step
        et_weight = 1 - xgb_weight - rf_weight
        if et_weight >= 0:
            xgb_weights += [xgb_weight]
            rf_weights += [rf_weight]
            et_weights += [et_weight]

modelWeights = {"xgb":xgb_weights, "rf": rf_weights, "et": et_weights}

for i in range(len(modelWeights.values()[0])):
	identity = ""
	totalPrediction = np.zeros(yhat.shape)
	for name in modelResults.keys():
		identity += name + "_" + str(modelWeights[name][i]) + ";"
		totalPrediction += modelWeights[name][i] * modelResults[name]
	error = rmspe(X_valid.Sales.values, np.expm1(totalPrediction))
	results[identity] = error

results = sorted(results.items(), key=operator.itemgetter(1))
print "\n\nfinal results: " + str(results[:15])
