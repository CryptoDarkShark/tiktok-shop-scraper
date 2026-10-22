"""usage: python3 nct.py "Company Kft." ... : nemzeticegtar lookup"""
import sys, json, requests, time
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import verify
s = requests.Session()
for c in sys.argv[1:]:
    print(c, json.dumps(verify.nct_lookup(c, s), ensure_ascii=False)); time.sleep(2)
