package dev.nocs.web;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

/**
 * Forwards GETs that don't match a REST mapping or a static asset to /index.html so that React Router
 * deep-links (e.g. /sequences/42) work from a fresh browser load.
 *
 * <p>This is mapped only to extension-less paths under /, so /api/** and /assets/**.* are not affected.
 */
@Controller
public class WebSpaController {

    @GetMapping(
            value = {
                "/",
                "/targets",
                "/mount",
                "/plate-solve",
                "/camera",
                "/filter-wheel",
                "/focuser",
                "/sequences",
                "/sequences/{id:[0-9]+}",
                "/gallery",
                "/sessions",
                "/sessions/{id:[0-9]+}",
                "/safety",
                "/settings"
            })
    public String spa() {
        return "forward:/index.html";
    }
}
