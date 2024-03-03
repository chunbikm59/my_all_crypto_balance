import requests
import json
import hmac
import hashlib
import time
import base64
from base64 import b64encode
from urllib.parse import urlencode
import datetime

# 幣安
BINANCE_API_KEY = '' 
BINANCE_API_SECRET = '' 
# Max
MAX_ACCESS_KEY = ''
MAX_SECRET_KEY = ''
# 幣托
BITOPRO_API_KEY = ''
BITOPRO_API_SECRET = ''
BITOPRO_EMAIL = '' # 幣托帳號信箱
BITOPRO_QUERY_START_TIME = '2020-4-1' # 幣托api查詢入金與出金紀錄時需設定開始時間

class BinanceAPI:
    def __init__(self, api_key, secret_key):
        self.API_KEY = api_key
        self.API_SECRET = secret_key

    def get_server_time(self):
        res = requests.get('https://api.binance.com/api/v3/time')
        return res.json()['serverTime']

    def create_signature(self, data):
        return hmac.new(self.API_SECRET.encode('utf-8'), data.encode('utf-8'), hashlib.sha256).hexdigest()

    def get_api(self, url):
        timestamp = self.get_server_time()
        headers = {
            'X-MBX-APIKEY': self.API_KEY
        }
        params = {
            'timestamp': timestamp,
            'recvWindow': 5000  # 
        }
        params['signature'] = self.create_signature('&'.join(f'{k}={v}' for k, v in params.items()))
        res = requests.get(url, headers=headers, params=params)
        return res.json()
    
    # 總餘額，以btc計價
    def get_total_balance(self):
        balances = self.get_api('https://api.binance.com/sapi/v1/asset/wallet/balance')
        total= sum([float(balance['balance']) for balance in balances])
        return total

class MaxAPI():
    def __init__(self, access_key, secret_key):
        self.access_key = access_key
        self.secret_key = secret_key

    def generate_signature(self, secret_key, payload):
        signature = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return signature

    def make_request(self, method, path, params=None):
        if params is None:
            params = {}
        nonce = int(time.time() * 1000)
        params['nonce'] = nonce
        params_to_be_signed = {**params, 'path': path}
        payload = b64encode(json.dumps(params_to_be_signed).encode()).decode()
        signature = self.generate_signature(self.secret_key, payload)

        headers = {
            'X-MAX-ACCESSKEY': self.access_key,
            'X-MAX-PAYLOAD': payload,
            'X-MAX-SIGNATURE': signature,
            'Content-Type': 'application/json',
        }

        url = f'https://max-api.maicoin.com{path}?{urlencode(params)}' if method == 'GET' else f'https://max-api.maicoin.com{path}'

        if method == 'GET':
            response = requests.get(url, headers=headers)
        elif method == 'POST':
            response = requests.post(url, data=json.dumps(params), headers=headers)
        else:
            raise ValueError('Unsupported HTTP method')

        data = response.json()
        return data
    
    # 依照幣種進行聚合加總
    def agg_sum(self, data, key, status=None):
        result_dict = {}
        for d in data:
            if d['status'] == status:
                if d['currency'] not in result_dict:
                    result_dict[d['currency']] = float(d[key])
                else:
                    result_dict[d['currency']] += float(d[key])

        return result_dict
    
    # 依市價轉換持有貨幣的價格
    def transfer_to_twd(self, data, tickers):
        total_twd = 0
        for currency in data:
            if data[currency] != 0:
                if currency=='twd':
                    price = 1
                else:
                    price = float(tickers[f'{currency}twd']['buy'])
                total_twd += data[currency] * price
        
        return total_twd
    
    # 法幣入金總額(TWD入金-TWD出金)
    def get_all_fiat_deposits(self):
        deposits = self.make_request('GET', '/api/v2/deposits')
        withdrawals = self.make_request('GET', '/api/v2/withdrawals')
        self.deposits = self.agg_sum(deposits, 'amount', 'done')
        self.withdrawals = self.agg_sum(withdrawals, 'amount', 'ok')
        return self.deposits['twd'] - self.withdrawals['twd']
    
    # 所有幣的總市值
    def get_total_balance(self):
        accounts = self.make_request('GET', '/api/v2/members/accounts')
        accounts = {a['currency']:float(a['balance']) for a in accounts}
        tickers = self.make_request('GET', '/api/v2/tickers')
        balance = self.transfer_to_twd(accounts, tickers)
        return balance
    
    def get_price(self, currency='btc', type='buy'):
        tickers = self.make_request('GET', '/api/v2/tickers')
        price = float(tickers[f'{currency}twd'][type])
        return price

class BitoProAPI:
    def __init__(self, api_key, secret_key, email, data_start_time, baseUrl='https://api.bitopro.com/v3'):
        self.API_KEY = api_key
        self.API_SECRET = secret_key
        self.email = email
        self.baseUrl = baseUrl
        self.data_start_time = self.datetime_to_unix_milliseconds(data_start_time)

    def send_request(self, method, url, data=None, timeout=None):
        # generate payload
        params = {"identity": self.email, "nonce": int(time.time() * 1000)}

        # base64 encode to get payload
        payload = base64.urlsafe_b64encode(json.dumps(params).encode("utf-8")).decode("utf-8")

        # use api secret to get signature
        signature = hmac.new(
            bytes(self.API_SECRET, "utf-8"),
            bytes(payload, "utf-8"),
            hashlib.sha384,
        ).hexdigest()

        # combine these data into an HTTP request header
        headers = {
            "X-BITOPRO-APIKEY": self.API_KEY,
            "X-BITOPRO-PAYLOAD": payload,
            "X-BITOPRO-SIGNATURE": signature,
        }
        try:
            session = requests.Session()
            response = None
            if method == "GET":
                response = session.get(url, headers=headers, params=data, timeout=timeout)
            if method == "POST":
                response = session.post(url, headers=headers, json=data, timeout=timeout)
            if method == "DELETE":
                response = session.delete(url, headers=headers, timeout=timeout)

            return response.json()

        except Exception as ex:
            print(ex)

    def get_balance(self, ):
        # combine endpoint with baseUrl
        endpoint = "/accounts/balance"
        complete_url = self.baseUrl + endpoint

        # send http request to server
        balances = self.send_request(method="GET", url=complete_url)
        # 計算餘額
        total_balance = 0
        for balance in balances['data']:
            if balance['amount'] == '0':
                continue
            if balance['currency'] == 'twd':
                total_balance += float(balance['amount'])
            else:
                ticker = requests.get(self.baseUrl+ f"/tickers/{balance['currency']}_twd").json()['data']
                total_balance += float(balance['amount']) * float(ticker['lastPrice'])
        return total_balance
    
    def get_all_fiat_deposits(self):
        # 法幣入金
        deposit = self.send_request_rolling_sum(
            url=self.baseUrl+'/wallet/depositHistory/twd', 
        )
        # 法幣出金
        withdraw = self.send_request_rolling_sum(
            url=self.baseUrl+'/wallet/withdrawHistory/twd', 
        )
        return deposit-withdraw
    
    def send_request_rolling_sum(self, url, interval=90, method="GET"):
        summary = 0
        start_time = self.data_start_time
        records = {}
        while start_time < int(time.time() * 1000):  # 檢查開始時間是否超過目前時間
            res = self.send_request(
                method=method,
                url=url, 
                data={'startTimestamp':start_time, 'limit':100}
            )
            for w in res['data']:
                if w['id'] not in records:
                    records[w['id']] = True
                    summary += float(w['amount'].replace(',', ''))

            # 將開始時間增加90天（以秒為單位）
            start_time += interval * 24 * 60 * 60 * 1000
        return summary
    
    def datetime_to_unix_milliseconds(self, date_string):
        date_time_obj = datetime.datetime.strptime(date_string, '%Y-%m-%d')
        unix_timestamp = int(date_time_obj.timestamp() * 1000)
        
        return unix_timestamp
    
if __name__ == '__main__':
    balance = 0 # 交易所、錢包的總餘額(twd)
    deposit = 0 # 交易所法幣入金總額(twd)
    
    # Max
    maxapi = MaxAPI(MAX_ACCESS_KEY, MAX_SECRET_KEY)
    max_deposit = maxapi.get_all_fiat_deposits()
    max_balance = maxapi.get_total_balance()
    deposit += max_deposit # max入金總額
    balance += max_balance # max中總餘額
    btc_price = maxapi.get_price('btc', 'buy') # 當前btc/twd價格

    # 幣安
    bnance = BinanceAPI(BINANCE_API_KEY, BINANCE_API_SECRET)
    bnance_balance = bnance.get_total_balance()
    bnance_balance *= btc_price # 換算台幣
    balance += bnance_balance

    # Bitopro
    bitoproapi = BitoProAPI(BITOPRO_API_KEY, BITOPRO_API_SECRET, BITOPRO_EMAIL, BITOPRO_QUERY_START_TIME) # 幣托需要指定查詢開始日期
    botopro_balance = bitoproapi.get_balance()
    botopro_deposits = bitoproapi.get_all_fiat_deposits()
    deposit += botopro_deposits
    balance += botopro_balance

    # 其他冷、熱錢包地址
    # BTC
    btc_addresses = [
        'BTC錢包地址1', # 
        'BTC錢包地址2', 
        'BTC錢包地址3'
    ]
    for addr in btc_addresses:
        res = requests.get(f'https://api.blockcypher.com/v1/btc/main/addrs/{addr}').json()
        res['balance'] = res['balance'] * 0.00000001 * btc_price # 單位轉換(1聰 = 0.00000001btc)
        balance += res['balance']
    
    print('deposit:', deposit)
    print('balance:', balance)
    print('損益:', balance-deposit)
    print('ROI:', round((balance/deposit-1)*100, 2), '%')