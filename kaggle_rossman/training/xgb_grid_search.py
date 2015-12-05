import pandas as pd
import numpy as np
from sklearn.cross_validation import train_test_split
import xgboost as xgb
import operator

def create_feature_map(features):
    outfile = open('xgb.fmap', 'w')
    for i, feat in enumerate(features):
        outfile.write('{0}\t{1}\tq\n'.format(i, feat))
    outfile.close()

def rmspe(y, yhat):
    return np.sqrt(np.mean((yhat/y-1) ** 2))

def rmspe_xg(yhat, y):
    y = np.expm1(y.get_label())
    yhat = np.expm1(yhat)
    return "rmspe", rmspe(y,yhat)

# Gather some features
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
    features.append('PromoOpen')
    data['PromoOpen'] = 12 * (data.Year - data.Promo2SinceYear) + \
        (data.WeekOfYear - data.Promo2SinceWeek) / 4.0
    data['PromoOpen'] = data.PromoOpen.apply(lambda x: x if x > 0 else 0)
    data.loc[data.Promo2SinceYear == 0, 'PromoOpen'] = 0

    features.append('IsPromoMonth')
    month2str = {1:'Jan', 2:'Feb', 3:'Mar', 4:'Apr', 5:'May', 6:'Jun', \
             7:'Jul', 8:'Aug', 9:'Sept', 10:'Oct', 11:'Nov', 12:'Dec'}
    data['monthStr'] = data.Month.map(month2str)
    data.loc[data.PromoInterval == 0, 'PromoInterval'] = ''
    data['IsPromoMonth'] = 0
    for interval in data.PromoInterval.unique():
        if interval != '':
            for month in interval.split(','):
                data.loc[(data.monthStr == month) & (data.PromoInterval == interval), 'IsPromoMonth'] = 1

    return data


print("Load the training, test and store data using pandas")
types = {'CompetitionOpenSinceYear': np.dtype(int),
        'CompetitionOpenSinceMonth': np.dtype(int),
        'StateHoliday': np.dtype(str),
        'Promo2SinceWeek': np.dtype(int),
        'SchoolHoliday': np.dtype(float),
        'PromoInterval': np.dtype(str)}
train = pd.read_csv("../data/train.csv", parse_dates=[2], dtype=types)
test = pd.read_csv("../data/test.csv", parse_dates=[3], dtype=types)
store = pd.read_csv("../data/store.csv")

print("Assume store open, if not provided")
train.fillna(1, inplace=True)
test.fillna(1, inplace=True)

print("Consider only open stores for training. Closed stores wont count into the score.")
train = train[train["Open"] != 0]
print("Use only Sales bigger then zero. Simplifies calculation of rmspe")
train = train[train["Sales"] > 0]

train = pd.merge(train, store, on='Store')
test = pd.merge(test, store, on='Store')

features = []

build_features(features, train)
build_features([], test)

X_train, X_valid = train_test_split(train, test_size=0.012, random_state=10)
y_train = np.log1p(X_train.Sales)
y_valid = np.log1p(X_valid.Sales)
dtrain = xgb.DMatrix(X_train[features], y_train)
dvalid = xgb.DMatrix(X_valid[features], y_valid)
watchlist = [(dtrain, 'train'), (dvalid, 'eval')]

def getError(maxDepth, num_round):
    params = {"objective": "reg:linear",
        "booster" : "gbtree",
        "eta": 0.3,
        "max_depth": maxDepth,
        "subsample": 0.9,
        "colsample_bytree": 0.7,
        "silent": 1,
        "seed": 1337
        }
    num_boost_round = num_round

    gbm = xgb.train(params, dtrain, num_boost_round, evals=watchlist, \
        early_stopping_rounds=100, feval=rmspe_xg, verbose_eval=True)
    yhat = gbm.predict(xgb.DMatrix(X_valid[features]))
    error = rmspe(X_valid.Sales.values, np.expm1(yhat))
    return error

maxDepths = [9, 10, 11, 12]
rounds = [300]
results = {}

for maxDepth in maxDepths:
    for num_round in rounds:
        print "currently: maxdepth->" + str(maxDepth) + " num_round->" + str(num_round)
        results[str(maxDepth) + "_" + str(num_round)] = getError(maxDepth, num_round) 

print results
