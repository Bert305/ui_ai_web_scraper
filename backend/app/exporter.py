import io
import json
import pandas as pd
from fastapi.responses import StreamingResponse
from typing import Dict, List, Any


def export_json(data: List[Dict[str, Any]]) -> StreamingResponse:
    file = io.BytesIO()
    file.write(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))
    file.seek(0)

    return StreamingResponse(
        file,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=scraped_data.json"},
    )


def export_csv(data: List[Dict[str, Any]]) -> StreamingResponse:
    df = pd.DataFrame(data)

    file = io.StringIO()
    df.to_csv(file, index=False)
    file.seek(0)

    return StreamingResponse(
        iter([file.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=scraped_data.csv"},
    )
