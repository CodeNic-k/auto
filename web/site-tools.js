/* Shared comments and owner-only editing for website and note cards. */
window.createSiteTools = function createSiteTools(db) {
  let canEdit = false;

  const style = document.createElement("style");
  style.textContent = `
    .site-auth{margin-left:auto;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
    .site-auth-status,.comment-meta,.tool-message{color:#67708a;font-size:.86rem}
    .tool-button{border:1px solid #dfe2ec;border-radius:9px;padding:7px 11px;background:#fff;color:#373064;font:inherit;font-weight:650;cursor:pointer}
    .tool-button:hover{border-color:#8d84e8;background:#f8f7ff}
    .auth-panel,.edit-panel{display:grid;gap:9px;margin:10px 0;padding:13px;border:1px solid #e3e7f0;border-radius:12px;background:#fafaff}
    .auth-panel[hidden],.edit-panel[hidden]{display:none}
    .auth-panel input,.edit-panel input,.edit-panel textarea,.comment-form input,.comment-form textarea{width:100%;min-height:42px;padding:9px 11px;border:1px solid #dfe2ec;border-radius:9px;background:#fff;color:#20243a;font:inherit}
    .edit-panel textarea,.comment-form textarea{min-height:100px;resize:vertical}
    .discussion{margin-top:16px;padding-top:13px;border-top:1px solid #e8eaf1}
    .discussion h3{margin:0 0 9px;font-size:.98rem}
    .comment-list{display:grid;gap:8px;margin-bottom:12px}
    .comment{padding:9px 11px;border-radius:10px;background:#f7f8fc;white-space:pre-wrap;overflow-wrap:anywhere}
    .comment p{margin:3px 0 0}
    .comment-form{display:grid;gap:8px}
    .tool-message[data-error="true"]{color:#a12626}
    @media(max-width:620px){.site-auth{margin-left:0;width:100%}}
  `;
  document.head.appendChild(style);

  const nav = document.querySelector('nav[aria-label="Main navigation"]');
  let authPanel;
  let authStatus;
  let toggleAuth;
  if (nav) {
    const authBox = document.createElement("div");
    authBox.className = "site-auth";
    authStatus = document.createElement("span");
    authStatus.className = "site-auth-status";
    toggleAuth = document.createElement("button");
    toggleAuth.type = "button";
    toggleAuth.className = "tool-button";
    toggleAuth.textContent = "Editor sign in";
    authBox.append(authStatus, toggleAuth);

    authPanel = document.createElement("form");
    authPanel.className = "auth-panel";
    authPanel.hidden = true;
    const email = document.createElement("input");
    email.type = "email";
    email.autocomplete = "username";
    email.placeholder = "Editor email";
    email.required = true;
    const password = document.createElement("input");
    password.type = "password";
    password.autocomplete = "current-password";
    password.placeholder = "Password";
    password.required = true;
    const submit = document.createElement("button");
    submit.className = "tool-button";
    submit.textContent = "Sign in";
    submit.type = "submit";
    const feedback = document.createElement("span");
    feedback.className = "tool-message";
    authPanel.append(email, password, submit, feedback);
    nav.insertAdjacentElement("afterend", authPanel);
    nav.appendChild(authBox);

    toggleAuth.addEventListener("click", async () => {
      const { data } = await db.auth.getSession();
      if (data.session) {
        await db.auth.signOut();
        return;
      }
      authPanel.hidden = !authPanel.hidden;
      feedback.textContent = "";
    });
    authPanel.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      feedback.dataset.error = "false";
      feedback.textContent = "Signing in…";
      const { error } = await db.auth.signInWithPassword({
        email: email.value.trim(), password: password.value,
      });
      submit.disabled = false;
      if (error) {
        feedback.dataset.error = "true";
        feedback.textContent = error.message;
        return;
      }
      password.value = "";
      authPanel.hidden = true;
    });
  }

  async function refreshEditor() {
    const { data } = await db.auth.getSession();
    canEdit = false;
    if (data.session) {
      const { data: allowed, error } = await db.rpc("is_site_editor");
      canEdit = !error && allowed === true;
      authStatus.textContent = canEdit ? "Editor signed in" : "Signed in · read only";
      toggleAuth.textContent = "Sign out";
    } else if (authStatus) {
      authStatus.textContent = "";
      toggleAuth.textContent = "Editor sign in";
    }
    document.dispatchEvent(new Event("site-editor-change"));
  }

  db.auth.onAuthStateChange(() => setTimeout(refreshEditor, 0));
  const ready = refreshEditor();

  async function loadComments(rows, type) {
    const grouped = new Map();
    const ids = rows.map((row) => row.id).filter((id) => id !== null && id !== undefined);
    for (let offset = 0; offset < ids.length; offset += 100) {
      const { data, error } = await db.from("content_comments")
        .select("id,target_type,target_id,video_id,author_name,body,created_at")
        .eq("target_type", type)
        .in("target_id", ids.slice(offset, offset + 100))
        .order("created_at", { ascending: true });
      if (error) throw error;
      for (const comment of data || []) {
        const key = `${type}:${comment.target_id}`;
        if (!grouped.has(key)) grouped.set(key, []);
        grouped.get(key).push(comment);
      }
    }
    return grouped;
  }

  function message(parent, value, isError = false) {
    const node = document.createElement("div");
    node.className = "tool-message";
    node.dataset.error = String(isError);
    node.textContent = value;
    parent.appendChild(node);
    return node;
  }

  function attach(card, item, type, detailNode, comments, onChanged) {
    if (canEdit) {
      const editButton = document.createElement("button");
      editButton.type = "button";
      editButton.className = "tool-button";
      editButton.textContent = "Edit";
      editButton.setAttribute("aria-label", type === "link" ? "Edit website description" : "Edit note");
      const panel = document.createElement("form");
      panel.className = "edit-panel";
      panel.hidden = true;
      let titleInput = null;
      if (type === "note") {
        titleInput = document.createElement("input");
        titleInput.value = item.title || "";
        titleInput.maxLength = 200;
        titleInput.setAttribute("aria-label", "Note title");
        panel.appendChild(titleInput);
      }
      const editor = document.createElement("textarea");
      editor.required = true;
      editor.maxLength = 12000;
      editor.setAttribute("aria-label", type === "link" ? "Website description" : "Note details");
      editor.value = type === "link" ? (item.description || "") : (item.detail || "");
      const save = document.createElement("button");
      save.type = "submit";
      save.className = "tool-button";
      save.textContent = "Save changes";
      const feedback = document.createElement("span");
      feedback.className = "tool-message";
      panel.append(editor, save, feedback);
      editButton.addEventListener("click", () => { panel.hidden = !panel.hidden; });
      panel.addEventListener("submit", async (event) => {
        event.preventDefault();
        save.disabled = true;
        feedback.textContent = "Saving…";
        feedback.dataset.error = "false";
        const values = type === "link"
          ? { description: editor.value.trim(), manually_edited: true }
          : { title: titleInput.value.trim(), detail: editor.value.trim(), manually_edited: true };
        const table = type === "link" ? "links" : "notes";
        const { error } = await db.from(table).update(values).eq("id", item.id);
        save.disabled = false;
        if (error) {
          feedback.dataset.error = "true";
          feedback.textContent = error.message;
          return;
        }
        await onChanged();
      });
      card.append(editButton, panel);
    }

    const section = document.createElement("section");
    section.className = "discussion";
    const heading = document.createElement("h3");
    heading.textContent = `Comments (${comments.length})`;
    section.appendChild(heading);
    const list = document.createElement("div");
    list.className = "comment-list";
    for (const entry of comments) {
      const box = document.createElement("article");
      box.className = "comment";
      const meta = document.createElement("div");
      meta.className = "comment-meta";
      const date = new Date(entry.created_at);
      meta.textContent = `${entry.author_name || "Visitor"} · ${date.toLocaleString()}`;
      const body = document.createElement("p");
      body.textContent = entry.body;
      box.append(meta, body);
      list.appendChild(box);
    }
    if (!comments.length) message(list, "No comments yet.");
    section.appendChild(list);

    const form = document.createElement("form");
    form.className = "comment-form";
    const name = document.createElement("input");
    name.maxLength = 80;
    name.placeholder = "Your name (optional)";
    name.setAttribute("aria-label", "Your name, optional");
    const body = document.createElement("textarea");
    body.required = true;
    body.maxLength = 2000;
    body.placeholder = "Add a comment or remember why this is useful…";
    body.setAttribute("aria-label", "Comment");
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "tool-button";
    submit.textContent = "Add comment";
    const feedback = document.createElement("span");
    feedback.className = "tool-message";
    form.append(name, body, submit, feedback);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      feedback.dataset.error = "false";
      feedback.textContent = "Saving comment…";
      const { error } = await db.from("content_comments").insert({
        target_type: type,
        target_id: item.id,
        video_id: item.video_id,
        author_name: name.value.trim() || null,
        body: body.value.trim(),
      });
      submit.disabled = false;
      if (error) {
        feedback.dataset.error = "true";
        feedback.textContent = error.message;
        return;
      }
      await onChanged();
    });
    section.appendChild(form);
    card.appendChild(section);
  }

  return { ready, loadComments, attach };
};
