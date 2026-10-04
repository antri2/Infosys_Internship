/* Career Assistant response normalization and safe Markdown rendering. */
(function (global) {
    'use strict';

    function normalizeResponse(value, depth) {
        depth = depth || 0;
        if (value === null || value === undefined || depth > 4) return '';

        if (typeof value === 'string') {
            var text = value.trim();
            if (!text) return '';
            var first = text.charAt(0);
            var last = text.charAt(text.length - 1);
            if ((first === '{' && last === '}') || (first === '[' && last === ']')) {
                try {
                    return normalizeResponse(JSON.parse(text), depth + 1);
                } catch (error) {
                    // It is ordinary text that happens to begin with a bracket.
                }
            }
            // Handle a backend/proxy that returned escaped content without a
            // valid outer JSON envelope.
            return text
                .replace(/\\r\\n/g, '\n')
                .replace(/\\n/g, '\n')
                .replace(/\\t/g, '\t')
                .replace(/\\"/g, '"')
                .replace(/\\'/g, "'");
        }

        if (Array.isArray(value)) {
            var parts = [];
            value.forEach(function (item) {
                var part = normalizeResponse(item, depth + 1);
                if (part) parts.push(part);
            });
            return parts.join('\n');
        }

        if (typeof value === 'object') {
            var keys = ['answer', 'response', 'content', 'message', 'text'];
            for (var index = 0; index < keys.length; index += 1) {
                var key = keys[index];
                if (Object.prototype.hasOwnProperty.call(value, key)) {
                    var candidate = normalizeResponse(value[key], depth + 1);
                    if (candidate) return candidate;
                }
            }
        }

        return '';
    }

    function appendTextWithBreaks(parent, text, doc) {
        String(text === null || text === undefined ? '' : text).split('\n').forEach(function (line, index) {
            if (index > 0) parent.appendChild(doc.createElement('br'));
            parent.appendChild(doc.createTextNode(line));
        });
    }

    function appendInline(parent, text, doc) {
        var source = String(text === null || text === undefined ? '' : text);
        var pattern = /(\*\*[^*\n]+\*\*|__[^_\n]+__|`[^`\n]+`|\*[^*\n]+\*|_[^_\n]+_|\[[^\]]+\]\(https?:\/\/[^)\s]+\))/g;
        var cursor = 0;
        var match;

        function appendPlain(value) {
            appendTextWithBreaks(parent, value, doc);
        }

        while ((match = pattern.exec(source)) !== null) {
            if (match.index > cursor) appendPlain(source.slice(cursor, match.index));
            var token = match[0];
            if (token.indexOf('**') === 0 || token.indexOf('__') === 0) {
                var strong = doc.createElement('strong');
                appendTextWithBreaks(strong, token.slice(2, -2), doc);
                parent.appendChild(strong);
            } else if (token.charAt(0) === '`') {
                var code = doc.createElement('code');
                appendTextWithBreaks(code, token.slice(1, -1), doc);
                parent.appendChild(code);
            } else if (token.charAt(0) === '[') {
                var linkMatch = token.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
                if (linkMatch) {
                    var link = doc.createElement('a');
                    link.href = linkMatch[2];
                    link.target = '_blank';
                    link.rel = 'noopener noreferrer';
                    appendTextWithBreaks(link, linkMatch[1], doc);
                    parent.appendChild(link);
                } else {
                    appendPlain(token);
                }
            } else {
                var emphasis = doc.createElement('em');
                appendTextWithBreaks(emphasis, token.slice(1, -1), doc);
                parent.appendChild(emphasis);
            }
            cursor = match.index + token.length;
        }
        if (cursor < source.length) appendPlain(source.slice(cursor));
    }

    function renderMarkdown(target, source) {
        if (!target) return target;
        var doc = target.ownerDocument || document;
        var text = String(source === null || source === undefined ? '' : source)
            .replace(/\r\n/g, '\n')
            .replace(/\r/g, '\n');
        var lines = text.split('\n');
        var fragment = doc.createDocumentFragment();
        var paragraph = [];
        var list = null;
        var listType = null;
        var lastListItem = null;

        function clearList() {
            list = null;
            listType = null;
            lastListItem = null;
        }

        function flushParagraph() {
            if (!paragraph.length) return;
            var p = doc.createElement('p');
            appendInline(p, paragraph.join('\n'), doc);
            fragment.appendChild(p);
            paragraph = [];
        }

        function ensureList(ordered) {
            var nextType = ordered ? 'ol' : 'ul';
            if (list && listType === nextType) return list;
            clearList();
            list = doc.createElement(nextType);
            listType = nextType;
            fragment.appendChild(list);
            return list;
        }

        lines.forEach(function (rawLine) {
            var line = rawLine.replace(/\s+$/, '');
            if (!line.trim()) {
                flushParagraph();
                return;
            }

            var continuation = line.match(/^\s{2,}(?!\s*(?:[-*+]|\d+[.)])\s+)(.+)$/);
            if (list && lastListItem && continuation) {
                lastListItem.appendChild(doc.createElement('br'));
                appendInline(lastListItem, continuation[1], doc);
                return;
            }

            var heading = line.match(/^\s*(#{1,6})\s+(.+?)\s*#*\s*$/);
            if (heading) {
                flushParagraph();
                clearList();
                var level = Math.min(heading[1].length, 6);
                var headingElement = doc.createElement('h' + level);
                appendInline(headingElement, heading[2], doc);
                fragment.appendChild(headingElement);
                return;
            }

            if (/^\s*(?:[-*_]\s*){3,}$/.test(line)) {
                flushParagraph();
                clearList();
                fragment.appendChild(doc.createElement('hr'));
                return;
            }

            var item = line.match(/^\s*(\d+[.)]|[-*+])\s+(.+)$/);
            if (item) {
                flushParagraph();
                var ordered = /^\d/.test(item[1]);
                var currentList = ensureList(ordered);
                var li = doc.createElement('li');
                appendInline(li, item[2], doc);
                currentList.appendChild(li);
                lastListItem = li;
                return;
            }

            if (list) clearList();
            paragraph.push(line);
        });

        flushParagraph();
        clearList();
        target.replaceChildren(fragment);
        return target;
    }

    var api = {
        normalizeResponse: normalizeResponse,
        renderMarkdown: renderMarkdown
    };

    global.CareerAssistantRendering = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
}(typeof window !== 'undefined' ? window : globalThis));
