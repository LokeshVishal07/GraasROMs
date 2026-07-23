"""Shared evidence helpers: saving (file upload or cloud link), listing, and the
Streamlit widgets used to preview/download evidence from the Damaged Queue,
Returns detail page, Marketplace Claims page, and the Evidence Repository."""
import datetime as dt
import io
import zipfile

import streamlit as st

from lib.db import get_session, Evidence

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
LINK_DOMAINS = ("drive.google.com", "docs.google.com", "onedrive.live.com",
                 "1drv.ms", "sharepoint.com", "dropbox.com")


def is_probably_valid_link(url: str) -> bool:
    """Loose validation: must look like an http(s) URL. We don't hard-block
    domains outside the known cloud-storage set (private company file servers
    etc. are legitimate too), but we do flag it back to the caller."""
    url = (url or "").strip()
    return url.startswith("http://") or url.startswith("https://")


def is_known_cloud_domain(url: str) -> bool:
    url = (url or "").strip().lower()
    return any(d in url for d in LINK_DOMAINS)


def save_uploaded_file(order_key: str, uploaded_file, user_name: str, when=None, category: str = None) -> None:
    session = get_session()
    try:
        session.add(Evidence(
            order_key=order_key, is_link=False,
            filename=uploaded_file.name, content_type=uploaded_file.type,
            size=uploaded_file.size, data=uploaded_file.getvalue(),
            uploaded_by=user_name, uploaded_at=when or dt.datetime.utcnow(),
            category=category,
        ))
        session.commit()
    finally:
        session.close()


def save_link(order_key: str, url: str, user_name: str, when=None, category: str = None) -> None:
    session = get_session()
    try:
        session.add(Evidence(
            order_key=order_key, is_link=True,
            filename=None, content_type=None, size=None, data=None,
            link_url=url.strip(), uploaded_by=user_name, uploaded_at=when or dt.datetime.utcnow(),
            category=category,
        ))
        session.commit()
    finally:
        session.close()


def list_evidence(order_key: str, category: str = None):
    """category=None (the default) returns every evidence row for the order,
    same as before -- callers that don't care about categories (Returns page,
    Damaged Queue, Evidence Repository, general Claims gallery) are
    unaffected. Pass category="pod" / "appeal" to scope to just that tagged
    subset, as used by the Marketplace Claims POD/Appeal sections."""
    session = get_session()
    try:
        q = session.query(Evidence).filter_by(order_key=order_key)
        if category is not None:
            q = q.filter_by(category=category)
        return q.order_by(Evidence.uploaded_at.desc()).all()
    finally:
        session.close()


def has_any_evidence(order_key: str) -> bool:
    session = get_session()
    try:
        return session.query(Evidence).filter_by(order_key=order_key).count() > 0
    finally:
        session.close()


def zip_evidence_files(evidence_list) -> bytes:
    """Bundles every file-type Evidence row's raw bytes into a ZIP. Link-type
    rows can't be bundled as files, so their URLs are collected into a
    links.txt manifest inside the same archive instead of being silently
    dropped."""
    buf = io.BytesIO()
    links = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seen_names = {}
        for ev in evidence_list:
            if ev.is_link:
                links.append(f"{ev.link_url}  (added by {ev.uploaded_by or '—'})")
                continue
            if not ev.data:
                continue
            name = ev.filename or f"evidence_{ev.id}"
            n = seen_names.get(name, 0)
            seen_names[name] = n + 1
            if n:
                base, _, ext = name.rpartition(".")
                name = f"{base or name}_{n}.{ext}" if ext else f"{name}_{n}"
            zf.writestr(name, ev.data)
        if links:
            zf.writestr("links.txt", "\n".join(links))
    return buf.getvalue()


def render_evidence_item(ev, key_prefix: str = "") -> None:
    """Renders one Evidence row: thumbnail (if it's an image), filename/size,
    who uploaded it and when, and preview/download/open/copy actions."""
    with st.container(border=True):
        c1, c2 = st.columns([1, 3])
        with c1:
            if ev.is_link:
                st.markdown("🔗", help="Cloud storage link")
            elif ev.filename and ev.filename.lower().endswith(IMAGE_EXTS) and ev.data:
                try:
                    st.image(ev.data, width=110)
                except Exception:
                    st.markdown("🖼️", help="Preview unavailable — the image data may be corrupted.")
            elif ev.content_type and ev.content_type.startswith("video"):
                st.markdown("🎬")
            else:
                st.markdown("📄")
        with c2:
            if ev.is_link:
                st.write(f"**Cloud storage link**")
                st.caption(ev.link_url)
            else:
                st.write(f"**{ev.filename or 'Untitled file'}**")
                if ev.size:
                    st.caption(f"{ev.content_type or 'file'} · {ev.size / 1024:.1f} KB")
            st.caption(f"Uploaded by {ev.uploaded_by or '—'} on "
                       f"{ev.uploaded_at.strftime('%d %b %Y, %H:%M') if ev.uploaded_at else '—'}")

            if ev.is_link:
                st.link_button("Open link", ev.link_url, width="stretch")
                st.code(ev.link_url, language=None)
            else:
                if ev.data:
                    if ev.filename and ev.filename.lower().endswith(IMAGE_EXTS):
                        with st.expander("Preview"):
                            try:
                                st.image(ev.data, width="stretch")
                            except Exception:
                                st.caption("Preview unavailable — the image data may be corrupted. "
                                           "You can still download the original file below.")
                    st.download_button(
                        "Download", data=ev.data, file_name=ev.filename or f"evidence_{ev.id}",
                        mime=ev.content_type or "application/octet-stream",
                        key=f"{key_prefix}_dl_{ev.id}", width="stretch",
                    )


def render_evidence_gallery(order_key: str, key_prefix: str = "", category: str = None,
                             empty_caption: str = "No evidence uploaded yet.") -> list:
    """Renders evidence rows for an order and returns the list, so callers
    (e.g. the claims page) can also offer a 'download all as ZIP' button.
    category=None (default) shows everything, matching prior behavior."""
    items = list_evidence(order_key, category=category)
    if not items:
        st.caption(empty_caption)
        return items
    cols = st.columns(2)
    for i, ev in enumerate(items):
        with cols[i % 2]:
            render_evidence_item(ev, key_prefix=f"{key_prefix}_{order_key}")
    if len(items) > 1:
        st.download_button(
            "Download all as ZIP", data=zip_evidence_files(items),
            file_name=f"evidence_{order_key}.zip", mime="application/zip",
            key=f"{key_prefix}_zipall_{order_key}",
        )
    return items
