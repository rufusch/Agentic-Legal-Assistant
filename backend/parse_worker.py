"""Parser subprocess protocol. Only bounded source bytes enter; no source text is logged."""
import json
import sys

from backend.parsing import ParseFailure, extract


if __name__ == '__main__':
    try:
        result = extract(sys.stdin.buffer.read(25 * 1024 * 1024 + 1), sys.argv[1])
        print(json.dumps({'result': result}))
    except ParseFailure as exc:
        print(json.dumps({'failure': {'code': exc.code, 'message': exc.message, 'retryable': False}}))
    except Exception:
        print(json.dumps({'failure': {'code': 'DOCUMENT_PROCESSING_FAILED', 'message': 'Document could not be read. Check its format or supply a clearer source.', 'retryable': False}}))
