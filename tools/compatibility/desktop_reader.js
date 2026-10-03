// Open the shipped reader and observe actual PDF rendering and PNG cache output.
async function observeAcceptanceReader(operation, libraryID) {
  const attachment = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.key);
  const reader = await Zotero.Reader.open(attachment.id);
  await reader._initPromise;
  await reader._internalReader._primaryView.initializedPromise;
  const window = reader._internalReader._primaryView._iframeWindow;
  const deadline = Date.now() + 60000;
  let canvas;
  let annotation = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.annotation);
  while (true) {
    canvas = window.document.querySelector('.page[data-page-number="1"] canvas');
    if (canvas?.width && canvas.height && window.PDFViewerApplication?.pdfViewer.getPageView(0)?.renderingState === 3
      && await Zotero.Annotations.hasCacheImage(annotation)) break;
    if (Date.now() > deadline) throw new Error("Reader did not render the page and cache an image annotation");
    await Zotero.Promise.delay(100);
  }
  const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
  const colors = new Map();
  for (let i = 0; i < pixels.length; i += 4) {
    const color = `${pixels[i]},${pixels[i + 1]},${pixels[i + 2]}`;
    colors.set(color, (colors.get(color) || 0) + 1);
  }
  // Zotero's dark theme changes actual canvas colors. The fixture still has
  // two contrasting regions, with its 80x80 square occupying 16% of the page.
  const dominant = [...colors].sort((a, b) => b[1] - a[1]).slice(0, 2);
  const fraction = dominant[1]?.[1] / (pixels.length / 4);
  const brightness = color => color.split(",").map(Number).reduce((a, b) => a + b, 0);
  const contrast = dominant.length === 2 ? Math.abs(brightness(dominant[0][0]) - brightness(dominant[1][0])) : 0;
  if (contrast < 300 || fraction < 0.1 || fraction > 0.22) {
    const data = atob(canvas.toDataURL("image/png").split(",")[1]);
    await IOUtils.write(operation.capture, Uint8Array.from(data, char => char.charCodeAt(0)));
    throw new Error(`Rendered PDF lacks the expected square: ${contrast}/${fraction}`);
  }
  const bytes = await IOUtils.read(Zotero.Annotations.getCacheImagePath(annotation));
  if (Array.from(bytes.subarray(0, 8)).join() !== "137,80,78,71,13,10,26,10") throw new Error("Reader annotation cache is not a PNG");
  let binary = "";
  for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
  return {width: canvas.width, height: canvas.height, png: btoa(binary)};
}
