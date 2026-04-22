package dev.nocs.indi;

import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.Deque;

/**
 * Extracts complete top-level XML elements from a UTF-8 byte buffer (INDI sends concatenated XML
 * fragments without a single root).
 */
final class IndiFragmentSplitter {

    private final StringBuilder utf8Buffer = new StringBuilder();

    void clear() {
        utf8Buffer.setLength(0);
    }

    void append(byte[] b, int off, int len) {
        utf8Buffer.append(new String(b, off, len, StandardCharsets.UTF_8));
    }

    /**
     * @return a complete XML fragment, or {@code null} if the buffer does not yet contain one full
     *     element.
     */
    String pollFragment() {
        String s = utf8Buffer.toString();
        int end = findFirstCompleteTopLevelElement(s, 0);
        if (end < 0) {
            return null;
        }
        String frag = s.substring(0, end).trim();
        utf8Buffer.delete(0, end);
        return frag.isEmpty() ? null : frag;
    }

    /**
     * Finds the end index (exclusive) of the first complete XML element starting at {@code from},
     * or {@code -1} if incomplete or no element.
     */
    static int findFirstCompleteTopLevelElement(String s, int from) {
        int i = skipWs(s, from);
        if (i >= s.length() || s.charAt(i) != '<') {
            return -1;
        }
        if (s.startsWith("<?", i)) {
            int e = s.indexOf("?>", i);
            return e < 0 ? -1 : e + 2;
        }
        Deque<String> stack = new ArrayDeque<>();
        int pos = i;
        OpenTag first = parseOpenTag(s, pos);
        if (first == null) {
            return -1;
        }
        if (first.selfClosing) {
            return first.endExclusive;
        }
        stack.push(first.name);
        pos = first.endExclusive;
        while (!stack.isEmpty()) {
            if (pos >= s.length()) {
                return -1;
            }
            int lt = s.indexOf('<', pos);
            if (lt < 0) {
                return -1;
            }
            if (s.startsWith("<!--", lt)) {
                int ce = s.indexOf("-->", lt);
                if (ce < 0) {
                    return -1;
                }
                pos = ce + 3;
                continue;
            }
            if (s.startsWith("<![CDATA[", lt)) {
                int ce = s.indexOf("]]>", lt);
                if (ce < 0) {
                    return -1;
                }
                pos = ce + 3;
                continue;
            }
            if (s.charAt(lt + 1) == '/') {
                CloseTag ct = parseCloseTag(s, lt);
                if (ct == null) {
                    return -1;
                }
                if (stack.isEmpty() || !stack.peek().equals(ct.name)) {
                    return -1;
                }
                stack.pop();
                pos = ct.endExclusive;
                if (stack.isEmpty()) {
                    return pos;
                }
                continue;
            }
            OpenTag child = parseOpenTag(s, lt);
            if (child == null) {
                return -1;
            }
            if (child.selfClosing) {
                pos = child.endExclusive;
                continue;
            }
            stack.push(child.name);
            pos = child.endExclusive;
        }
        return -1;
    }

    private static int skipWs(String s, int i) {
        while (i < s.length() && Character.isWhitespace(s.charAt(i))) {
            i++;
        }
        return i;
    }

    private record OpenTag(String name, boolean selfClosing, int endExclusive) {}

    private record CloseTag(String name, int endExclusive) {}

    private static OpenTag parseOpenTag(String s, int lt) {
        if (lt < 0 || lt >= s.length() || s.charAt(lt) != '<') {
            return null;
        }
        int nameStart = lt + 1;
        if (nameStart >= s.length()) {
            return null;
        }
        int nameEnd = nameStart;
        while (nameEnd < s.length()) {
            char c = s.charAt(nameEnd);
            if (c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '/' || c == '>') {
                break;
            }
            nameEnd++;
        }
        if (nameEnd == nameStart) {
            return null;
        }
        String name = s.substring(nameStart, nameEnd);
        int j = nameEnd;
        boolean inQuote = false;
        char quote = 0;
        while (j < s.length()) {
            char c = s.charAt(j);
            if (inQuote) {
                if (c == quote) {
                    inQuote = false;
                }
                j++;
                continue;
            }
            if (c == '"' || c == '\'') {
                inQuote = true;
                quote = c;
                j++;
                continue;
            }
            if (c == '>') {
                int k = j - 1;
                while (k >= nameEnd && Character.isWhitespace(s.charAt(k))) {
                    k--;
                }
                boolean selfClosing = k >= nameEnd && s.charAt(k) == '/';
                return new OpenTag(name, selfClosing, j + 1);
            }
            j++;
        }
        return null;
    }

    private static CloseTag parseCloseTag(String s, int lt) {
        int gt = s.indexOf('>', lt);
        if (gt < 0) {
            return null;
        }
        String inner = s.substring(lt + 2, gt).trim();
        return new CloseTag(inner, gt + 1);
    }
}
