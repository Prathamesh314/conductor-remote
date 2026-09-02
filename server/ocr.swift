// OCR an image file with the Vision framework.
// Usage:  ocr <image-path>
// Prints JSON: [{"text","x","y","w","h"}] where x/y are the CENTER of each
// text box in NORMALIZED coords (0..1). x from left, y from TOP.
//
// The screenshot itself is taken separately with the `screencapture` CLI (which
// owns Screen Recording permission), so this program uses no deprecated capture
// API and works on current macOS.

import Foundation
import Vision
import CoreGraphics
import ImageIO

let args = CommandLine.arguments
guard args.count > 1 else {
    FileHandle.standardError.write(Data("usage: ocr <image-path>\n".utf8))
    exit(1)
}

let url = URL(fileURLWithPath: args[1])
guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
    FileHandle.standardError.write(Data("ERROR: cannot load image \(args[1])\n".utf8))
    exit(2)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false

let handler = VNImageRequestHandler(cgImage: image, options: [:])
do {
    try handler.perform([request])
} catch {
    FileHandle.standardError.write(Data("ERROR: OCR failed: \(error)\n".utf8))
    exit(3)
}

var out: [[String: Any]] = []
for obs in (request.results ?? []) {
    guard let cand = obs.topCandidates(1).first else { continue }
    let bb = obs.boundingBox                    // normalized, origin bottom-left
    out.append([
        "text": cand.string,
        "x": bb.origin.x + bb.size.width / 2,
        "y": 1.0 - (bb.origin.y + bb.size.height / 2),   // top-origin
        "w": bb.size.width,
        "h": bb.size.height,
    ])
}

let data = try JSONSerialization.data(withJSONObject: out, options: [])
FileHandle.standardOutput.write(data)
