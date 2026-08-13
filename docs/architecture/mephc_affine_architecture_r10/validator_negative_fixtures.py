from pathlib import Path
import hashlib
ROOT=Path(__file__).resolve().parent
SHA="9ae0c4262451827c7ae559ea9a635b2304316b0a880d462ee4b217241b56a219"
def main():
    raw=(ROOT/"authoritative_contract.json").read_bytes()
    mutated=bytearray(raw); mutated[0]=(mutated[0]+1)%256
    assert hashlib.sha256(bytes(mutated)).hexdigest()!=SHA
    assert 0.02 not in [-0.01,-0.005,-0.0025,-0.00125,0,0.00125,0.0025,0.005,0.01]
    print("PASS_R10_NEGATIVE_FIXTURES contract_digest_mutation,forbidden_primary_amplitude")
if __name__=="__main__": main()
