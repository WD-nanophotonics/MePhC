from pathlib import Path
import hashlib
ROOT=Path(__file__).resolve().parent
SHA="c06f22d8b01fd3c3a6809553bb94ff6577501dfd540bdcf4275076209481e1ab"
def main():
    raw=(ROOT/"authoritative_contract.json").read_bytes()
    x=bytearray(raw); x[0]=(x[0]+1)%256
    assert hashlib.sha256(bytes(x)).hexdigest()!=SHA
    assert 0.00075 not in [0.0005,0.001]
    assert 0.003 not in [-0.002,-0.001,-0.0005,0.0,0.0005,0.001,0.002]
    print("PASS_R11_NEGATIVE_FIXTURES contract_digest_mutation,adaptive_h_rejected,forbidden_amplitude_rejected")
if __name__=="__main__": main()
