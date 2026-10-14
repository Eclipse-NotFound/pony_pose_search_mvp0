// Auditable Animate command template; generated requests contain only JSON data.
// ES3-compatible: Animate 24.0.4 has no global JSON implementation.
// This file never launches Animate, installs extensions, saves documents, or runs scripts.
(function () {
    var request = __PONY_CHARACTER_REQUEST__;
    var owned = null, previous = null, receiptWritable = false;
    var receipt = {
        schema_version: 'character_fla_export_v1',
        export_id: request.export_id,
        request_sha256: request.request_sha256,
        copy_uri: request.copy_uri,
        operation: request.operation,
        state: 'failed',
        renderer: {name: 'Adobe Animate', version: String(fl.version)},
        timelines: [], frames: [], exported_count: 0
    };

    function fail(code, message) {
        var error = new Error(message);
        error.code = code;
        throw error;
    }
    function own(object, key) {
        return Object.prototype.hasOwnProperty.call(object, key);
    }
    function stringify(value) {
        var parts = [], key;
        if (value === null || typeof value === 'undefined') return 'null';
        if (typeof value === 'boolean') return value ? 'true' : 'false';
        if (typeof value === 'number') return isFinite(value) ? String(value) : 'null';
        if (typeof value === 'string') {
            return '"' + value.replace(/[\\"\u0000-\u001f\u2028\u2029]/g, function (c) {
                return '\\u' + ('0000' + c.charCodeAt(0).toString(16)).slice(-4);
            }) + '"';
        }
        if (value instanceof Array) {
            for (key = 0; key < value.length; key++) parts.push(stringify(value[key]));
            return '[' + parts.join(',') + ']';
        }
        for (key in value) if (own(value, key) && typeof value[key] !== 'function') {
            parts.push(stringify(key) + ':' + stringify(value[key]));
        }
        return '{' + parts.join(',') + '}';
    }
    function errorData(error) {
        return {code: String(error.code || 'HOST_ERROR'),
            message: String(error.message || error), line: error.lineNumber || null};
    }
    function integer(value) {
        return typeof value === 'number' && isFinite(value) && Math.floor(value) === value;
    }
    function pathKey(uri) {
        return FLfile.uriToPlatformPath(uri).replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
    }
    function localURI(uri) {
        if (typeof uri !== 'string' || !/^file:\/\//i.test(uri)) {
            fail('LOCAL_URI_REQUIRED', 'A local file URI is required.');
        }
    }
    function documentStillOpen(document) {
        var documents = fl.documents || [], i;
        for (i = 0; i < documents.length; i++) if (documents[i] === document) return true;
        return false;
    }
    function recordCleanupError(error) {
        receipt.state = 'failed';
        if (!receipt.cleanup_errors) receipt.cleanup_errors = [];
        receipt.cleanup_errors.push(errorData(error));
    }
    function symbolItems(document) {
        var output = [], items = document.library.items, i, item;
        for (i = 0; i < items.length; i++) {
            item = items[i];
            if ((item.itemType === 'graphic' || item.itemType === 'movie clip' || item.itemType === 'button') && item.timeline) {
                output.push(item);
            }
        }
        return output;
    }
    function directReferences(document) {
        var refs = {}, s, l, f, e, timeline, layer, frame, element;
        for (s = 0; s < document.timelines.length; s++) {
            timeline = document.timelines[s];
            for (l = 0; l < timeline.layers.length; l++) {
                layer = timeline.layers[l];
                for (f = 0; f < layer.frames.length; f++) {
                    frame = layer.frames[f];
                    if (!frame || frame.startFrame !== f) continue;
                    for (e = 0; e < frame.elements.length; e++) {
                        element = frame.elements[e];
                        if (element.elementType === 'instance' && element.libraryItem) {
                            refs['item:' + element.libraryItem.name] = true;
                        }
                    }
                }
            }
        }
        return refs;
    }
    function composite(timeline) {
        var layersWithContent = 0, l, f, layer, frame, layerHasContent;
        for (l = 0; l < timeline.layers.length; l++) {
            layer = timeline.layers[l]; layerHasContent = false;
            for (f = 0; f < layer.frames.length; f++) {
                frame = layer.frames[f];
                if (!frame || frame.startFrame !== f) continue;
                if (frame.elements.length > 1) return true;
                if (frame.elements.length) layerHasContent = true;
            }
            if (layerHasContent) layersWithContent++;
            if (layersWithContent > 1) return true;
        }
        return false;
    }
    function inspect(document) {
        var rows = [], refs = directReferences(document), items = symbolItems(document), i, timeline, item, recommended;
        for (i = 0; i < document.timelines.length; i++) {
            timeline = document.timelines[i];
            rows.push({id: 'scene:' + i, kind: 'scene', name: String(timeline.name || ''),
                frame_count: timeline.frameCount, index0: i, suggested: true,
                reason: 'Scene timeline; review whether it contains a complete character.'});
        }
        for (i = 0; i < items.length; i++) {
            item = items[i];
            recommended = !!refs['item:' + item.name] && composite(item.timeline);
            rows.push({id: 'symbol:' + item.name, kind: 'symbol', name: String(item.name),
                frame_count: item.timeline.frameCount, index0: null, suggested: recommended,
                reason: recommended ?
                    'Composite symbol directly referenced by a scene; completeness is not confirmed.' :
                    'Library symbol; may be a part, variant, or unreferenced character.'});
        }
        return rows;
    }
    function framesFor(target) {
        var frames = request.frames0, i;
        if (!(frames instanceof Array) || !frames.length || frames.length > 2048) {
            fail('FRAME_RANGE', 'Select between 1 and 2048 source frames.');
        }
        for (i = 0; i < frames.length; i++) {
            if (!integer(frames[i]) || frames[i] < 0 || frames[i] >= target.frame_count ||
                    (i && frames[i] <= frames[i - 1])) {
                fail('FRAME_RANGE', 'Source frames must be increasing, unique, and inside the timeline.');
            }
        }
        return frames;
    }
    function pngFiles(directory) {
        var names = FLfile.listFolder(directory, 'files'), output = [], i;
        if (!names) fail('OUTPUT_LIST_FAILED', 'Cannot enumerate the export directory.');
        for (i = 0; i < names.length; i++) if (/\.png$/i.test(names[i])) output.push(names[i]);
        return output;
    }
    function assertImage(directory, name) {
        if (!name || /[\\/]/.test(name) || !FLfile.exists(directory + '/' + name) ||
                FLfile.getSize(directory + '/' + name) <= 8) {
            fail('PNG_MISSING', 'Native export did not produce a nonempty PNG file: ' + name);
        }
        // PNG decoding, dimensions and SHA-256 are checked by the importer.
    }
    function renderScene(document, target, frames, directory) {
        var index = target.index0, timeline, i, name, uri;
        if (!integer(index) || index < 0 || index >= document.timelines.length || target.id !== 'scene:' + index) {
            fail('SCENE_MISMATCH', 'The requested scene identity is invalid.');
        }
        timeline = document.timelines[index];
        if (String(timeline.name || '') !== target.name || timeline.frameCount !== target.frame_count) {
            fail('TIMELINE_CHANGED', 'Scene name or frame count differs from the inspected version.');
        }
        document.currentTimeline = index;
        if (document.currentTimeline !== index || document.getTimeline().name !== timeline.name ||
                document.getTimeline().frameCount !== timeline.frameCount) {
            fail('SCENE_MISMATCH', 'Animate did not select the requested scene.');
        }
        for (i = 0; i < frames.length; i++) {
            timeline.currentFrame = frames[i];
            if (timeline.currentFrame !== frames[i]) fail('FRAME_MISMATCH', 'Animate did not select the requested frame.');
            name = 'frame_' + ('000000' + (frames[i] + 1)).slice(-6) + '.png';
            uri = directory + '/' + name;
            if (FLfile.exists(uri)) fail('OUTPUT_EXISTS', 'Refusing to overwrite an exported image.');
            if (!document.exportPNG(uri, true, true)) fail('EXPORT_FAILED', 'Animate reported a failed PNG export.');
            assertImage(directory, name);
            receipt.frames.push({frame_index0: frames[i], file: name, timeline_id: target.id});
            receipt.exported_count++;
        }
    }
    function renderSymbol(document, target, frames, directory) {
        var items = symbolItems(document), item = null, i, names, entries = [], match, start;
        if (target.id !== 'symbol:' + target.name) fail('SYMBOL_MISMATCH', 'The requested symbol identity is invalid.');
        for (i = 0; i < items.length; i++) if (items[i].name === target.name) {
            if (item) fail('SYMBOL_AMBIGUOUS', 'More than one library symbol has the requested exact name.');
            item = items[i];
        }
        if (!item || item.timeline.frameCount !== target.frame_count) {
            fail('TIMELINE_CHANGED', 'Library symbol is missing or its frame count changed.');
        }
        if (target.frame_count > 2048) fail('EXPORT_LIMIT', 'A full symbol export is limited to 2048 frames.');
        if (typeof item.exportToPNGSequence !== 'function') fail('EXPORT_UNAVAILABLE', 'This Animate host cannot export a symbol sequence.');
        // Deliberately omit start/end: the official symbol API does not define their index base.
        // It returns nothing; only the complete directory and continuous numbering establish success.
        item.exportToPNGSequence(directory + '/symbol_frame.png');
        names = pngFiles(directory);
        receipt.exported_count = names.length;
        if (names.length !== target.frame_count) fail('SEQUENCE_COUNT', 'Native sequence count differs from the complete symbol timeline.');
        if (names.length === 1 && /^symbol_frame\.png$/i.test(names[0])) {
            entries.push({number: 0, name: names[0]});
        } else {
            for (i = 0; i < names.length; i++) {
                match = /^symbol_frame[_-]?(\d+)\.png$/i.exec(names[i]);
                if (!match) fail('SEQUENCE_NAME', 'Unexpected native sequence filename: ' + names[i]);
                entries.push({number: Number(match[1]), name: names[i]});
            }
            entries.sort(function (a, b) { return a.number - b.number; });
            start = entries[0].number;
            if (start !== 0 && start !== 1) fail('SEQUENCE_BASE', 'Native sequence must start at zero or one.');
            for (i = 0; i < entries.length; i++) if (entries[i].number !== start + i) {
                fail('SEQUENCE_GAP', 'Native sequence numbering is duplicated or incomplete.');
            }
        }
        for (i = 0; i < entries.length; i++) assertImage(directory, entries[i].name);
        for (i = 0; i < frames.length; i++) {
            receipt.frames.push({frame_index0: frames[i], file: entries[frames[i]].name, timeline_id: target.id});
        }
    }

    try {
        localURI(request.result_uri);
        if (FLfile.exists(request.result_uri)) fail('RESULT_EXISTS', 'This request already has a receipt; it will not be replayed or overwritten.');
        receiptWritable = true;
        localURI(request.copy_uri); localURI(request.output_uri);
        if (request.operation !== 'inspect' && request.operation !== 'render') fail('OPERATION', 'Unsupported export operation.');
        if (!FLfile.exists(request.copy_uri)) fail('COPY_MISSING', 'The registered private FLA copy does not exist.');
        if (pathKey(request.copy_uri) === pathKey(request.result_uri)) fail('PATH_COLLISION', 'The source copy cannot be the output receipt.');
        var before = fl.documents || [], beforeDocuments = [], i, document, copyKey = pathKey(request.copy_uri);
        for (i = 0; i < before.length; i++) {
            beforeDocuments.push(before[i]);
            if (before[i].pathURI && pathKey(before[i].pathURI) === copyKey) {
                fail('COPY_ALREADY_OPEN', 'The registered copy is already open; do not adopt or close it.');
            }
        }
        previous = fl.getDocumentDOM();
        document = fl.openDocument(request.copy_uri);
        if (!document || !document.pathURI || pathKey(document.pathURI) !== copyKey) {
            fail('OPEN_FAILED', 'Animate did not open the exact registered private copy.');
        }
        for (i = 0; i < beforeDocuments.length; i++) if (document === beforeDocuments[i]) {
            fail('COPY_ALREADY_OPEN', 'Animate returned an existing document; do not adopt or close it.');
        }
        owned = document;
        receipt.frame_rate = document.frameRate;
        receipt.width = document.width; receipt.height = document.height;
        if (request.operation === 'inspect') {
            receipt.timelines = inspect(document);
        } else {
            var target = request.timeline, directory = request.output_uri.replace(/\/+$/, ''), frames;
            if (!target || !integer(target.frame_count) || target.frame_count < 1 || typeof target.name !== 'string') {
                fail('TIMELINE_INVALID', 'The requested timeline metadata is invalid.');
            }
            frames = framesFor(target);
            if (!FLfile.exists(directory) && !FLfile.createFolder(directory)) fail('OUTPUT_DIRECTORY', 'Cannot create the private export directory.');
            // Empty means no prior partial sequence can be mistaken for this request's output.
            if (FLfile.listFolder(directory).length) fail('OUTPUT_NOT_EMPTY', 'Refusing to mix this render with existing output files.');
            receipt.timeline = target;
            if (target.kind === 'scene') renderScene(document, target, frames, directory);
            else if (target.kind === 'symbol') renderSymbol(document, target, frames, directory);
            else fail('TIMELINE_KIND', 'Only scene and library symbol timelines are supported.');
        }
        receipt.state = 'done';
    } catch (error) {
        receipt.state = 'failed'; receipt.error = errorData(error);
    } finally {
        if (owned) {
            try { owned.close(false); }
            catch (closeError) { recordCleanupError(closeError); }
        }
        if (previous && documentStillOpen(previous)) {
            try { fl.setActiveWindow(previous); }
            catch (restoreError) { recordCleanupError(restoreError); }
        }
    }
    // A prior receipt is immutable, including failed and partial runs. No automatic replay.
    if (!receiptWritable) fail(receipt.error ? receipt.error.code : 'RESULT_NOT_WRITABLE',
        receipt.error ? receipt.error.message : 'No new receipt was written.');
    if (FLfile.exists(request.result_uri)) fail('RESULT_EXISTS', 'A receipt appeared during execution; refusing to overwrite it.');
    if (!FLfile.write(request.result_uri, stringify(receipt))) fail('RESULT_WRITE', 'Failed to write the export receipt.');
    if (receipt.state !== 'done') fl.trace('Character FLA export failed: ' + stringify(receipt.error || receipt.cleanup_errors));
}());
