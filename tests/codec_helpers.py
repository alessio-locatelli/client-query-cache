from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from bson.codec_options import CodecOptions, TypeDecoder, TypeRegistry
from bson.decimal128 import Decimal128
from bson.raw_bson import RawBSONDocument

if TYPE_CHECKING:
    from decimal import Decimal


class Decimal128ToDecimalDecoder(TypeDecoder):
    bson_type = Decimal128

    @override
    def transform_bson(self, value: Decimal128) -> Decimal:
        return value.to_decimal()


def decode_only_decimal_options() -> CodecOptions[RawBSONDocument]:
    return CodecOptions(
        document_class=RawBSONDocument,
        type_registry=TypeRegistry([Decimal128ToDecimalDecoder()]),
    )


@dataclass(frozen=True, slots=True)
class DecodedPriceCase[CollectionType]:
    collection: CollectionType
    email: str
    price: Decimal
