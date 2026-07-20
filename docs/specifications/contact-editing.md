# Contact Editing — Specification

**Date:** 2026-07-20
**Status:** Draft

---

## Objective

Allow users to edit existing contact details inline on the Opportunity Modal (leads card) without navigating away.

---

## Current State

- **Display only**: Primary contact and all contacts list show name, email, phone, LinkedIn, notes — but no edit capability
- **Delete/add only**: Each contact has a trash (delete) button; adding happens via a separate form at the top
- **Backend ready**: `PATCH /contacts/{contactId}` exists with `ContactUpdate` schema (`first_name`, `last_name`, `job_title`, `email`, `phone_direct`, `phone_mobile`, `linkedin_url`, `is_primary`, `notes` — all optional)
- **Frontend API wired**: `contacts.update(contactId, body)` exists in `api.ts` but is never called
- **No edit state**: No `editingContactId`, `editForm`, or related state variables

---

## Design

### Contact list item (lines 531–574 of `OpportunityModal.tsx`)

Each contact row currently has:
```
[Name + Primary Badge + Job Title]
[Email | Phone Direct | Phone Mobile | LinkedIn]
[Notes]
[Trash button]
```

**Add**: An **Edit (pencil) icon** next to the trash button. Clicking it enters edit mode for that contact.

**Edit mode**: The contact's fields become editable inline. The display values are replaced by input fields. A Save/Cancel pair replaces the Edit/Delete buttons.

### Edit state

Add state variables:
```typescript
const [editingContactId, setEditingContactId] = useState<string | null>(null);
const [editForm, setEditForm] = useState<{
  first_name: string; last_name: string; job_title: string;
  email: string; phone_direct: string; phone_mobile: string;
  linkedin_url: string; is_primary: boolean; notes: string;
} | null>(null);
```

When edit is clicked for contact `c`:
```typescript
setEditingContactId(c.id);
setEditForm({
  first_name: c.first_name,
  last_name: c.last_name,
  job_title: c.job_title ?? '',
  email: c.email ?? '',
  phone_direct: c.phone_direct ?? '',
  phone_mobile: c.phone_mobile ?? '',
  linkedin_url: c.linkedin_url ?? '',
  is_primary: c.is_primary,
  notes: c.notes ?? '',
});
```

### Inline inputs

When `editingContactId === c.id` and `editForm` is set, render the contact as:

```
[First name input] [Last name input]
[Job title input]
[Email input]
[Phone direct input] [Phone mobile input]
[LinkedIn input]
[Is primary checkbox]
[Notes textarea]

[Save button] [Cancel button]
```

Each input is bound to `editForm[field]` via `onChange`.

### Save mutation

```typescript
const editContactMutation = useMutation({
  mutationFn: ({ id, body }: { id: string; body: Parameters<typeof contacts.update>[1] }) =>
    contacts.update(id, body),
  onSuccess: () => {
    invalidate();
    setEditingContactId(null);
    setEditForm(null);
  },
});
```

On save: call `editContactMutation.mutate({ id: editingContactId, body: editForm })`.

On cancel: `setEditingContactId(null); setEditForm(null);`

### Input styling

- Inputs match the existing "add contact" form style: `w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white`
- Save button: `rounded bg-primary-500 px-3 py-1 text-xs text-white hover:bg-primary-400`
- Cancel button: `rounded px-3 py-1 text-xs text-gray-400 hover:text-white`

### Primary contact targeting

If `is_primary` is toggled on a non-primary contact, the backend `PATCH /contacts/{id}` should handle it. The existing backend already supports setting `is_primary` via `ContactUpdate`.

---

## Files to change

### `frontend/src/components/OpportunityModal.tsx`
- Add `editingContactId`, `editForm` state variables
- Add `editContactMutation` (wires to `contacts.update()`)
- Add `handleEditContact(c)` — populates editForm
- Add `handleSaveEdit()` — calls mutation
- Add `handleCancelEdit()` — clears state
- In the contact list loop (line 531): branch on `editingContactId === c.id`
  - If editing: render inputs bound to `editForm`
  - If not editing: render existing display + add Pencil icon before Trash icon
- Import `Pencil` from `lucide-react` (add to existing import)

### No backend changes needed
The `PATCH /contacts/{contactId}` endpoint and `ContactUpdate` schema already support all fields.

---

## Acceptance criteria

1. Each contact in the list has an edit (pencil) icon alongside the existing trash icon
2. Clicking edit replaces the contact's display with editable inputs
3. All contact fields are editable: first name, last name, job title, email, phone direct, phone mobile, LinkedIn URL, primary flag, notes
4. Save persists via `PATCH /contacts/{id}` and refreshes the opportunity data
5. Cancel reverts to the previous display without changes
6. Input styling matches the existing "add contact" form
7. The add contact form and delete functionality continue to work unchanged
