"""Kanoniczny transkrypt edukacyjnego RSA + DH."""

from hashlib import sha256
from typing import Annotated

from pydantic import Field, model_validator

from .internal_models import HexId, Model, PeerRole, PublicKey, UInt


class Transcript(Model):
    session_id: HexId
    backend_epoch: HexId
    signer: PeerRole
    prime: Annotated[UInt, Field(ge=3)]
    generator: Annotated[UInt, Field(ge=2)]
    alice_public: UInt
    bob_public: UInt
    alice_key: PublicKey
    bob_key: PublicKey

    @model_validator(mode='after')
    def dh_ranges(self):
        if max(self.generator, self.alice_public, self.bob_public) >= self.prime:
            raise ValueError('Parametry transkryptu poza zakresem DH.')
        return self

    def encode(self) -> bytes:
        return '\n'.join((
            'RADH-SIGNED-DH-V1',
            f'session_id={self.session_id}',
            f'backend_epoch={self.backend_epoch}',
            f'signer={self.signer}',
            f'prime={self.prime}',
            f'generator={self.generator}',
            f'alice_public={self.alice_public}',
            f'bob_public={self.bob_public}',
            f'alice_rsa_n={self.alice_key.modulus}',
            f'alice_rsa_e={self.alice_key.public_exponent}',
            f'bob_rsa_n={self.bob_key.modulus}',
            f'bob_rsa_e={self.bob_key.public_exponent}',
        )).encode('ascii')

    def hash_and_representative(self) -> tuple[str, int]:
        key = self.alice_key if self.signer == 'alice' else self.bob_key
        digest = sha256(self.encode()).digest()
        return digest.hex(), int.from_bytes(digest, 'big') % key.modulus
