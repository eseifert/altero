"""Render a valid PDF and generate image annotations through the shipped reader."""

from tools.compatibility.acceptance_runtime import AcceptanceRun


def reader_pdf() -> bytes:
    """A deterministic one-page PDF with a black square on a white background."""
    content = b"0 0 0 rg 20 20 80 80 re f\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"endstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode() + value + b"\nendobj\n")
    xref = len(data)
    data.extend(b"xref\n0 5\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


async def reader_rendering(run: AcceptanceRun) -> None:
    path = run.root / "reader.pdf"
    path.write_bytes(reader_pdf())
    first = await run.phase(
        "A",
        [
            dict(action="create", key="READER23"),
            dict(action="attach", key="READER23", path=str(path)),
        ],
    )
    attachment = next(item["key"] for item in first["items"] if item["itemType"] == "attachment")
    await run.phase(
        "A",
        [
            dict(
                action="create",
                key="IMAGE234",
                data=dict(
                    itemType="annotation",
                    parentItem=attachment,
                    annotationType="image",
                    annotationColor="#ffd400",
                    annotationPageLabel="1",
                    annotationSortIndex="00000|000001|00000",
                    annotationPosition='{"pageIndex":0,"rects":[[20,20,80,80]]}',
                ),
            )
        ],
    )
    await run.phase("B")
    operation = dict(
        action="reader-open",
        key=attachment,
        annotation="IMAGE234",
        capture=str(run.root / "reader-canvas.png"),
    )
    left = await run.phase("A", [operation], sync=False)
    right = await run.phase("B", [operation], sync=False)
    assert left["reader"]["png"] == right["reader"]["png"]
    await run.phase(
        "A",
        [
            dict(
                action="json",
                key="IMAGE234",
                data=dict(annotationPosition='{"pageIndex":0,"rects":[[120,120,180,180]]}'),
            )
        ],
    )
    await run.phase("B")
    changed_left = await run.phase("A", [operation], sync=False)
    changed_right = await run.phase("B", [operation], sync=False)
    assert changed_left["reader"]["png"] != left["reader"]["png"], (
        "Position change retained a stale image"
    )
    assert changed_left["reader"]["png"] == changed_right["reader"]["png"]
    assert (await run.phase("B", [operation], sync=False))["reader"]["png"] == changed_right[
        "reader"
    ]["png"]
    await run.settled()
