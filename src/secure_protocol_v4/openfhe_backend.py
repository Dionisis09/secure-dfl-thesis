"""Public aggregation context. Each worker holds only its own private share."""
import numpy as np
from .core import Rejected

class MultipartyBFV:
    MODULUS=2013265921
    SCALE=65536
    def __init__(self,context=None,parties=3):
        import openfhe as f
        self.f=f
        if context is None:
            p=f.CCParamsBFVRNS();p.SetPlaintextModulus(self.MODULUS);p.SetMultiplicativeDepth(0);p.SetBatchSize(4096)
            p.SetSecurityLevel(f.HEStd_128_classic)
            p.SetMultipartyMode(f.NOISE_FLOODING_MULTIPARTY)
            p.SetThresholdNumOfParties(parties)
            self.cc=f.GenCryptoContext(p)
            for feature in [f.PKE,f.KEYSWITCH,f.LEVELEDSHE,f.MULTIPARTY]:self.cc.Enable(feature)
        else:self.cc=f.DeserializeCryptoContextString(context,f.BINARY)
    def dump(self,obj):return self.f.Serialize(obj,self.f.BINARY)
    def context(self):return self.dump(self.cc)
    def ciphertext(self,data):return self.f.DeserializeCiphertextString(data,self.f.BINARY)
    def keygen(self,previous=None):
        kp=self.cc.KeyGen() if previous is None else self.cc.MultipartyKeyGen(self.f.DeserializePublicKeyString(previous,self.f.BINARY))
        if not kp.good():raise Rejected('key generation failed')
        return kp.secretKey,self.dump(kp.publicKey)
    def encrypt(self,pk,values):
        key=self.f.DeserializePublicKeyString(pk,self.f.BINARY)
        integers=np.rint(np.asarray(values)*self.SCALE).astype(np.int64)
        return self.dump(self.cc.Encrypt(key,self.cc.MakePackedPlaintext(integers.tolist())))
    def average(self,payloads,n):
        if len(payloads)!=n:raise Rejected('incomplete ciphertext group')
        total=self.ciphertext(payloads[0])
        for data in payloads[1:]:total=self.cc.EvalAdd(total,self.ciphertext(data))
        return self.dump(total)
    def partial(self,data,secret,lead):
        method=self.cc.MultipartyDecryptLead if lead else self.cc.MultipartyDecryptMain
        return self.dump(method([self.ciphertext(data)],secret)[0])
    def fusion(self,payloads,spec):
        if len(payloads)!=len(spec.roster):raise Rejected('missing decryption share')
        p=self.cc.MultipartyDecryptFusion([self.ciphertext(data) for data in payloads]);p.SetLength(spec.length)
        integers=np.asarray(p.GetPackedValue(),dtype=np.int64)
        integers=np.where(integers>self.MODULUS//2,integers-self.MODULUS,integers)
        v=integers.astype(np.float64)/(self.SCALE*len(spec.roster))
        if v.shape!=(spec.length,) or not np.isfinite(v).all():raise Rejected('invalid recovered plaintext')
        return v

class CKKS:
    def __init__(self,*args,**kwargs):
        raise Rejected("CKKS disabled: verified multiparty noise-flooding build/parameters required; no insecure fallback")
