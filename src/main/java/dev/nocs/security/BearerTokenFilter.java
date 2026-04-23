package dev.nocs.security;

import dev.nocs.config.NocsProperties;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.List;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
public class BearerTokenFilter extends OncePerRequestFilter {

    private final String expectedToken;

    public BearerTokenFilter(NocsProperties props) {
        this.expectedToken = props.auth() == null ? null : props.auth().token();
    }

    @Override
    protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
            throws ServletException, IOException {
        String token = extractToken(req);
        if (token != null && expectedToken != null && !expectedToken.isBlank() && expectedToken.equals(token)) {
            var auth = new UsernamePasswordAuthenticationToken(
                    "nocs-user", null, List.of(new SimpleGrantedAuthority("ROLE_USER")));
            SecurityContextHolder.getContext().setAuthentication(auth);
        }
        chain.doFilter(req, res);
    }

    private static String extractToken(HttpServletRequest req) {
        String header = req.getHeader("Authorization");
        if (header != null && header.startsWith("Bearer ")) {
            return header.substring("Bearer ".length()).trim();
        }
        // Fallback: ?token=... — only honoured for GET /api/events and GET /api/images/**.
        String path = req.getRequestURI();
        if ("GET".equalsIgnoreCase(req.getMethod())
                && (path.equals("/api/events") || path.startsWith("/api/images/"))) {
            String t = req.getParameter("token");
            if (t != null && !t.isBlank()) {
                return t;
            }
        }
        return null;
    }
}
