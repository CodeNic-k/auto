/* Shared comments and owner-only editing for website and note cards. */
window.createSiteTools = function createSiteTools(db) {
  let canEdit = false;
  let commentsAvailable = true;
  let discussionNumber = 0;

  const style = document.createElement("style");
  style.textContent = `
    .site-auth{margin-left:auto;display:flex;align-items:center;gap:9px;flex-wrap:wrap}
    .site-auth-status,.comment-meta,.tool-message{color:#67708a;font-size:.86rem}
    .site-auth-status:not(:empty){padding:6px 10px;border-radius:999px;background:#f0efff;color:#4438bd;font-weight:650}
    .tool-button{border:1px solid #dfe2ec;border-radius:10px;padding:8px 12px;background:#fff;color:#373064;font:inherit;font-size:.92rem;font-weight:680;cursor:pointer;transition:background .15s,border-color .15s,transform .15s}
    .tool-button:hover{border-color:#8d84e8;background:#f8f7ff;transform:translateY(-1px)}
    .tool-button:focus-visible{outline:3px solid #5548d944;outline-offset:2px}
    .tool-button:disabled{cursor:wait;opacity:.65;transform:none}
    article.card:has(.card-actions){transition:border-color .18s,box-shadow .18s,transform .18s}
    article.card:has(.card-actions):hover{border-color:#d3d0f8;box-shadow:0 10px 28px #34306412;transform:translateY(-1px)}
    .auth-panel,.edit-panel{display:grid;gap:10px;margin:10px 0;padding:16px;border:1px solid #e3e7f0;border-radius:14px;background:linear-gradient(135deg,#fafaff,#f5f7ff)}
    .auth-panel[hidden],.edit-panel[hidden]{display:none}
    .card-actions>.edit-panel{flex:1 0 100%}
    .auth-panel input,.edit-panel input,.edit-panel textarea,.comment-form input,.comment-form textarea{width:100%;min-height:42px;padding:9px 11px;border:1px solid #dfe2ec;border-radius:9px;background:#fff;color:#20243a;font:inherit}
    .edit-panel textarea,.comment-form textarea{min-height:100px;resize:vertical}
    .card-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:auto;padding-top:12px}
    .discussion-toggle{display:inline-flex;align-items:center;gap:8px;color:#4e43c3}
    .discussion-toggle::after{content:"＋";font-size:1rem;line-height:1}
    .discussion-toggle[aria-expanded="true"]::after{content:"−"}
    .comment-count{display:inline-grid;place-items:center;min-width:22px;height:22px;padding:0 6px;border-radius:999px;background:#efedff;color:#4438bd;font-size:.78rem}
    .discussion-panel{margin-top:12px;padding:14px;border:1px solid #e7e8f1;border-radius:13px;background:#fbfbfe}
    .discussion-panel[hidden]{display:none}
    .comment-list{display:grid;gap:9px;margin-bottom:13px}
    .comment{padding:11px 13px;border:1px solid #eceef5;border-radius:11px;background:#fff;white-space:pre-wrap;overflow-wrap:anywhere}
    .comment p{margin:3px 0 0}
    .comment-form{display:grid;gap:9px;padding-top:12px;border-top:1px solid #e8eaf1}
    .comment-form input:focus,.comment-form textarea:focus,.edit-panel input:focus,.edit-panel textarea:focus,.auth-panel input:focus{outline:3px solid #5548d922;border-color:#766de0}
    .tag-area{display:flex;flex-wrap:wrap;align-items:center;gap:7px;margin:4px 0 12px}
    .tag-chip{display:inline-flex;align-items:center;gap:5px;padding:4px 9px;border:1px solid #e4e2fb;border-radius:999px;background:#f6f5ff;color:#4438bd;font-size:.82rem;text-decoration:none}
    .tag-chip:hover{border-color:#aaa4f5;background:#efedff}
    .tag-pending{color:#866318;background:#fff9e9;border-color:#f3e4b7}
    .tag-add{display:flex;flex-wrap:wrap;align-items:center;gap:7px;flex:1 0 100%}
    .tag-add[hidden]{display:none}
    .tag-add input{width:min(100%,220px);min-height:36px;padding:6px 10px;border:1px solid #dfe2ec;border-radius:9px;font:inherit}
    .tag-moderation{display:inline-flex;gap:4px;margin-left:4px}
    .tag-moderation button{padding:1px 5px;border:1px solid #e4dfca;border-radius:6px;background:#fff;font:inherit;font-size:.75rem;cursor:pointer}
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
      const helper = document.createElement("span");
      helper.className = "tool-message";
      helper.textContent = "Sign in with the Gmail account added to the site editor allowlist.";
    authPanel.append(email, password, helper, submit, feedback);
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
      authStatus.textContent = canEdit ? "Editor mode" : error ? "Editor setup needed" : "Signed in · read only";
      authStatus.title = canEdit ? "You can edit website descriptions and notes." : error
        ? "Apply site_collaboration.sql and allowlist this account to enable editing."
        : "This account is not on the site_editors allowlist.";
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
    commentsAvailable = true;
    for (let offset = 0; offset < ids.length; offset += 100) {
      try {
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
      } catch (error) {
        console.error("Could not load comments. Apply the site collaboration migration.", error);
        commentsAvailable = false;
        return new Map();
      }
    }
    return grouped;
  }

  async function loadTags(rows) {
    const grouped = new Map();
    const ids = rows.map((row) => row.id).filter((id) => id !== null && id !== undefined);
    for (let offset = 0; offset < ids.length; offset += 500) {
      const { data, error } = await db.from("link_tags")
        .select("id,link_id,tag,source,status,created_at")
        .in("link_id", ids.slice(offset, offset + 500))
        .order("tag", { ascending: true });
      if (error) throw error;
      for (const entry of data || []) {
        if (!grouped.has(entry.link_id)) grouped.set(entry.link_id, []);
        grouped.get(entry.link_id).push(entry);
      }
    }
    return grouped;
  }

  function attachTags(parent, item, tags, onChanged) {
    const area = document.createElement("div");
    area.className = "tag-area";
    const status = document.createElement("span");
    status.className = "tool-message";
    for (const entry of tags || []) {
      if (entry.status === "approved") {
        const chip = document.createElement("a");
        chip.className = "tag-chip";
        chip.textContent = `#${entry.tag}`;
        chip.href = `./index.html?tag=${encodeURIComponent(entry.tag)}`;
        chip.title = `Find websites tagged ${entry.tag}`;
        area.appendChild(chip);
      } else if (canEdit && entry.status === "pending") {
        const chip = document.createElement("span");
        chip.className = "tag-chip tag-pending";
        chip.textContent = `Pending: ${entry.tag}`;
        const controls = document.createElement("span");
        controls.className = "tag-moderation";
        for (const [label, next] of [["Approve", "approved"], ["Reject", "rejected"]]) {
          const action = document.createElement("button");
          action.type = "button";
          action.textContent = label;
          action.addEventListener("click", async () => {
            action.disabled = true;
            const { error } = await db.from("link_tags").update({ status: next }).eq("id", entry.id);
            if (error) { action.disabled = false; status.dataset.error = "true"; status.textContent = error.message; }
            else await onChanged();
          });
          controls.appendChild(action);
        }
        chip.appendChild(controls);
        area.appendChild(chip);
      }
    }
    const form = document.createElement("form");
    form.className = "tag-add";
    form.hidden = true;
    const input = document.createElement("input");
    input.maxLength = 40;
    input.minLength = 2;
    input.pattern = "[A-Za-z0-9][A-Za-z0-9 &._+-]{1,39}";
    input.placeholder = "Add a tag";
    input.setAttribute("aria-label", "Suggest a website tag");
    input.required = true;
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "tool-button";
    submit.textContent = canEdit ? "Add tag" : "Suggest tag";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "tool-button";
    toggle.textContent = canEdit ? "Add tag" : "Suggest tag";
    toggle.setAttribute("aria-expanded", "false");
    toggle.addEventListener("click", () => {
      form.hidden = !form.hidden;
      toggle.setAttribute("aria-expanded", String(!form.hidden));
      if (!form.hidden) input.focus();
    });
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "tool-button";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", () => {
      form.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      status.textContent = "";
      input.value = "";
    });
    form.append(input, submit, cancel);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const tag = input.value.trim().replace(/\s+/g, " ");
      const duplicate = (tags || []).some((entry) => entry.tag.toLowerCase() === tag.toLowerCase());
      if (duplicate) { status.textContent = "That tag already exists or has already been reviewed."; return; }
      submit.disabled = true;
      status.dataset.error = "false";
      status.textContent = canEdit ? "Adding tag…" : "Sending suggestion…";
      const { error } = await db.from("link_tags").insert({
        link_id: item.id, tag, source: "user", status: canEdit ? "approved" : "pending",
      });
      submit.disabled = false;
      if (error) { status.dataset.error = "true"; status.textContent = error.message || "Could not save this tag."; return; }
      if (!canEdit) status.textContent = "Thanks. Your tag will appear after an editor reviews it.";
      else await onChanged();
      input.value = "";
      form.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
    });
    area.append(toggle, form, status);
    parent.appendChild(area);
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
    const actions = document.createElement("div");
    actions.className = "card-actions";
    if (canEdit) {
      const editButton = document.createElement("button");
      editButton.type = "button";
      editButton.className = "tool-button";
      const editLabel = type === "link" ? "Edit description" : "Edit note";
      editButton.textContent = editLabel;
      editButton.setAttribute("aria-label", type === "link" ? "Edit website description" : "Edit note");
      const panel = document.createElement("form");
      panel.className = "edit-panel";
      panel.hidden = true;
      let titleInput = null;
      if (type === "note") {
        titleInput = document.createElement("input");
        titleInput.value = item.title || "";
        titleInput.maxLength = 200;
        titleInput.placeholder = "Note title";
        titleInput.setAttribute("aria-label", "Note title");
        panel.appendChild(titleInput);
      }
      const editor = document.createElement("textarea");
      editor.required = true;
      editor.maxLength = 12000;
      editor.placeholder = type === "link" ? "Edit the website description…" : "Edit the note details…";
      editor.setAttribute("aria-label", type === "link" ? "Website description" : "Note details");
      editor.value = type === "link" ? (item.description || "") : (item.detail || "");
      const save = document.createElement("button");
      save.type = "submit";
      save.className = "tool-button";
      save.textContent = "Save changes";
      const feedback = document.createElement("span");
      feedback.className = "tool-message";
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "tool-button";
      cancel.textContent = "Cancel";
      cancel.addEventListener("click", () => {
        panel.hidden = true;
        editButton.textContent = editLabel;
      });
      panel.append(editor, save, cancel, feedback);
      editButton.addEventListener("click", () => {
        panel.hidden = !panel.hidden;
        editButton.textContent = panel.hidden ? editLabel : "Cancel edit";
      });
      panel.addEventListener("submit", async (event) => {
        event.preventDefault();
        save.disabled = true;
        feedback.textContent = "Saving…";
        feedback.dataset.error = "false";
        const values = type === "link"
          ? { description: editor.value.trim(), manually_edited: true }
          : { title: titleInput.value.trim(), detail: editor.value.trim(), manually_edited: true };
        const table = type === "link" ? "links" : "notes";
        let error;
        try {
          ({ error } = await db.from(table).update(values).eq("id", item.id));
        } catch (requestError) {
          error = requestError;
        }
        save.disabled = false;
        if (error) {
          feedback.dataset.error = "true";
          feedback.textContent = error.message || "Could not save. Check your connection and editor permissions.";
          return;
        }
        await onChanged();
      });
      actions.append(editButton, panel);
    }

    const section = document.createElement("section");
    section.className = "discussion";
    discussionNumber += 1;
    const panelId = `comments-panel-${discussionNumber}`;
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "tool-button discussion-toggle";
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", panelId);
    toggle.append("Comments ");
    const count = document.createElement("span");
    count.className = "comment-count";
    count.textContent = String(comments.length);
    toggle.appendChild(count);
    actions.appendChild(toggle);

    const panel = document.createElement("div");
    panel.className = "discussion-panel";
    panel.id = panelId;
    panel.hidden = true;
    toggle.addEventListener("click", () => {
      panel.hidden = !panel.hidden;
      toggle.setAttribute("aria-expanded", String(!panel.hidden));
    });
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
    panel.appendChild(list);

    if (!commentsAvailable) {
      message(panel, "Comments are unavailable until the Supabase site collaboration migration is applied.", true);
    } else {

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
        let error;
        try {
          ({ error } = await db.from("content_comments").insert({
            target_type: type,
            target_id: item.id,
            video_id: item.video_id,
            author_name: name.value.trim() || null,
            body: body.value.trim(),
          }));
        } catch (requestError) {
          error = requestError;
        }
        submit.disabled = false;
        if (error) {
          feedback.dataset.error = "true";
          feedback.textContent = error.message || "Could not save the comment. Check your connection.";
          return;
        }
        await onChanged();
      });
      panel.appendChild(form);
    }
    section.appendChild(panel);
    card.append(actions, section);
  }

  return { ready, loadComments, loadTags, attachTags, attach };
};
