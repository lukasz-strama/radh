"""Ścisłe modele odpowiedzi internal v2; niezależne od koordynatora v1."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

HexId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$", strict=True)]
UInt = Annotated[int, Field(strict=True, ge=1, le=2**32-1)]
Revision = Annotated[int, Field(strict=True, ge=0)]
Role = Literal['alice', 'bob', 'mallory']
PeerRole = Literal['alice', 'bob']
Scenario = Literal['classic', 'authenticated']
ParticipantStatus = Literal['waiting', 'published', 'received', 'verified']
TranscriptHash = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$', strict=True)]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class SessionContext(Model):
    session_id: HexId
    backend_epoch: HexId


class Descriptor(SessionContext):
    prime: UInt
    generator: UInt
    mode: Literal['normal', 'mitm']
    scenario: Scenario
    diagnostics_enabled: bool
    status: Literal['created', 'running', 'completed', 'cancelled', 'expired', 'failed']
    revision: Revision
    expires_at: str
    remaining_ttl_seconds: Annotated[int, Field(strict=True, ge=0, le=600)]
    participant_status: ParticipantStatus | None
    diagnostics_received: bool

    @model_validator(mode='after')
    def parameters(self):
        if not 2 <= self.generator < self.prime:
            raise ValueError('Niepoprawne parametry.')
        if ((self.scenario == 'classic' and self.participant_status == 'verified')
                or (self.scenario == 'authenticated' and self.participant_status == 'received')):
            raise ValueError('Stan uczestnika nie pasuje do scenariusza.')
        date = datetime.fromisoformat(self.expires_at.replace('Z', '+00:00'))
        if date.tzinfo is None:
            raise ValueError('Wymagana strefa czasowa.')
        return self


class Discovery(Model):
    backend_epoch: HexId
    sessions: Annotated[list[Descriptor], Field(max_length=128)]
    retry_after_ms: Annotated[int, Field(strict=True, ge=1000, le=1000)]

    @model_validator(mode='after')
    def unique(self):
        if (len({d.session_id for d in self.sessions}) != len(self.sessions)
                or any(d.backend_epoch != self.backend_epoch for d in self.sessions)):
            raise ValueError('Niespójny snapshot.')
        return self


class Heartbeat(Model):
    backend_epoch: HexId
    instance_id: HexId
    lease_seconds: Annotated[int, Field(strict=True, ge=10, le=10)]


class Message(Model):
    message_id: Literal['alice-public', 'bob-public']
    sender: Literal['alice', 'bob']
    recipient: Literal['alice', 'bob']
    type: Literal['public_value']
    public_value: UInt
    status: Literal['intercepted', 'queued', 'processed']


class Inbox(Model):
    session_id: HexId
    backend_epoch: HexId
    revision: Revision
    messages: Annotated[list[Message], Field(max_length=1)]


class Interception(Model):
    message_id: Literal['alice-public', 'bob-public']
    original_sender: Literal['alice', 'bob']
    recipient: Literal['alice', 'bob']
    original_value: UInt
    delivered_value: UInt | None
    intercepted_by: Literal['mallory']
    actual_sender: Literal['mallory'] | None
    status: Literal['pending', 'forwarded', 'processed']

    @model_validator(mode='after')
    def routing(self):
        if (self.original_sender == self.recipient
                or self.message_id != self.original_sender + '-public'
                or (self.status == 'pending') != (self.delivered_value is None)
                or (self.status == 'pending') != (self.actual_sender is None)):
            raise ValueError('Niepoprawne przechwycenie.')
        return self


class Interceptions(Model):
    session_id: HexId
    backend_epoch: HexId
    revision: Revision
    interceptions: Annotated[list[Interception], Field(max_length=2)]

    @model_validator(mode='after')
    def unique(self):
        if len({i.message_id for i in self.interceptions}) != len(self.interceptions):
            raise ValueError('Powtórzone przechwycenie.')
        return self


class Participants(Model):
    alice: ParticipantStatus
    bob: ParticipantStatus


class PublicKey(Model):
    modulus: Annotated[int, Field(ge=256, le=2**32-1)]
    public_exponent: Annotated[int, Field(ge=2, le=2**32-1)]

    @model_validator(mode='after')
    def exponent_range(self):
        if self.public_exponent >= self.modulus:
            raise ValueError('Niepoprawny wykładnik publiczny RSA.')
        return self


class TrustedKey(SessionContext, PublicKey):
    owner: PeerRole


class Signature(SessionContext):
    signer: PeerRole
    transcript_hash: TranscriptHash
    signature: Annotated[int, Field(ge=0, le=2**32-1)]


class Verification(SessionContext):
    signer: PeerRole
    verifier: PeerRole
    transcript_hash: TranscriptHash
    published_transcript_hash: TranscriptHash
    verified: bool

    @model_validator(mode='after')
    def roles_and_hash(self):
        if self.verifier == self.signer or (
                self.verified and self.transcript_hash != self.published_transcript_hash):
            raise ValueError('Niespójny raport weryfikacji.')
        return self


class AuthenticationState(SessionContext):
    trusted_keys: Annotated[list[TrustedKey], Field(max_length=2)]
    signatures: Annotated[list[Signature], Field(max_length=2)]
    verifications: Annotated[list[Verification], Field(max_length=2)]

    @model_validator(mode='after')
    def matching_records(self):
        for records, role_field in ((self.trusted_keys, 'owner'), (self.signatures, 'signer'),
                                    (self.verifications, 'verifier')):
            if (len({getattr(record, role_field) for record in records}) != len(records)
                    or any(record.session_id != self.session_id or record.backend_epoch != self.backend_epoch
                           for record in records)):
                raise ValueError('Powtórzone dane uwierzytelniania lub dane innej sesji.')
        keys = {key.owner: key for key in self.trusted_keys}
        signatures = {signature.signer: signature for signature in self.signatures}
        if self.signatures and (len(keys) != 2 or any(
                signature.signature >= keys[signature.signer].modulus for signature in self.signatures)):
            raise ValueError('Podpis poza zakresem lub brak zaufanych kluczy RSA.')
        if self.verifications and len(signatures) != 2:
            raise ValueError('Weryfikacja wymaga obu podpisów.')
        for report in self.verifications:
            signature = signatures.get(report.signer)
            if signature is None or signature.transcript_hash != report.published_transcript_hash:
                raise ValueError('Raport odwołuje się do innego podpisu.')
        return self


class SessionView(SessionContext):
    prime: UInt
    generator: UInt
    mode: Literal['normal', 'mitm']
    scenario: Scenario
    diagnostics_enabled: bool
    status: Literal['created', 'running', 'completed', 'cancelled', 'expired', 'failed']
    failure_code: str | None
    created_at: str
    expires_at: str
    terminal_at: str | None
    revision: Revision
    participants: Participants
    messages: Annotated[list[Message], Field(max_length=2)]
    interceptions: Annotated[list[Interception], Field(max_length=2)]
    authentication: AuthenticationState

    @model_validator(mode='after')
    def authentication_context(self):
        if (self.authentication.session_id, self.authentication.backend_epoch) != (
                self.session_id, self.backend_epoch):
            raise ValueError('Dane uwierzytelniania innej sesji.')
        return self
