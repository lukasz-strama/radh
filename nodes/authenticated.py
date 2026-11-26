"""Lokalny stan podpisanego DH dla jednego uczestnika i jednej sesji."""

from backend.app.crypto_core import CryptoCore
from backend.app.parameter_generation import generate_rsa_keypair
from .internal_models import Descriptor, Message, PeerRole, PublicKey, Signature, TrustedKey, Verification
from .transcript import Transcript

RSA_KEY_ATTEMPTS = 256


class AuthenticatedExchange:
    def __init__(self, core: CryptoCore):
        self._core = core
        pair = generate_rsa_keypair(core, RSA_KEY_ATTEMPTS)
        self.public_key = PublicKey(modulus=pair.n, public_exponent=pair.e)
        self._private_exponent: int | None = pair.d
        self.key_published = False
        self.peer_key: TrustedKey | None = None
        self.peer_message: Message | None = None
        self.signature: Signature | None = None
        self.signature_published = False
        self.verification: Verification | None = None
        self.verification_published = False

    def transcript(self, descriptor: Descriptor, local_role: PeerRole, local_public: int,
                   signer: PeerRole) -> Transcript:
        assert self.peer_key is not None and self.peer_message is not None
        own = (local_public, self.public_key)
        peer = (self.peer_message.public_value, self.peer_key)
        alice, bob = (own, peer) if local_role == 'alice' else (peer, own)
        return Transcript(
            session_id=descriptor.session_id, backend_epoch=descriptor.backend_epoch,
            signer=signer, prime=descriptor.prime, generator=descriptor.generator,
            alice_public=alice[0], alice_key=alice[1], bob_public=bob[0], bob_key=bob[1],
        )

    def sign(self, transcript: Transcript) -> Signature:
        assert self._private_exponent is not None
        transcript_hash, h = transcript.hash_and_representative()
        signature = self._core.sign(h, self._private_exponent, self.public_key.modulus)
        self._private_exponent = None
        return Signature(
            session_id=transcript.session_id, backend_epoch=transcript.backend_epoch,
            signer=transcript.signer, transcript_hash=transcript_hash, signature=signature,
        )

    def verify(self, transcript: Transcript, signature: Signature, verifier: PeerRole) -> Verification:
        assert self.peer_key is not None
        transcript_hash, h = transcript.hash_and_representative()
        valid_signature = self._core.verify(
            h, signature.signature, self.peer_key.public_exponent, self.peer_key.modulus,
        )
        return Verification(
            session_id=transcript.session_id, backend_epoch=transcript.backend_epoch,
            signer=signature.signer, verifier=verifier, transcript_hash=transcript_hash,
            published_transcript_hash=signature.transcript_hash,
            verified=transcript_hash == signature.transcript_hash and valid_signature,
        )
