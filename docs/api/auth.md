# Authentication & Authorization API

Endpoints for user registration, JWT lifecycle, password reset, MFA, and OAuth providers.

> [!NOTE]
> Total verified endpoints documented: **28**.

### `POST` /v1/auth/accept-invite

**Accept Invite**

Public: redeem an invite token, set the first password, and log the user in.

#### Request Body (`application/json`)

Schema: `AcceptInviteIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/auth/invite-info

**Invite Info**

Public: validate an invite token and return who it's for (for the accept screen).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `token` | query | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/auth/login

**Login**

#### Request Body (`application/json`)

Schema: `LoginIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/auth/logout

**Logout**

Revoke the presented refresh token (this device/session). Unauthenticated: possession of
the signed token is the proof, so it works even after the access token expires (finding d).

#### Request Body (`application/json`)

Schema: `LogoutIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/auth/logout-all

**Logout All**

Sign out every session for the current user (all devices) by advancing their revocation
cutoff so all previously-issued access/refresh tokens are rejected (finding d).

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |

---

### `GET` /v1/auth/me

**Me**

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |

---

### `POST` /v1/auth/mfa/totp/confirm

**Totp Confirm**

#### Request Body (`application/json`)

Schema: `TotpCodeIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/auth/mfa/totp/disable

**Totp Disable**

Disable MFA. Requires a current code so a hijacked session can't silently turn it off.

#### Request Body (`application/json`)

Schema: `TotpCodeIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/auth/mfa/totp/enroll

**Totp Enroll**

Generate a TOTP secret (NOT yet active - confirm a code to enable). Returns the secret
and an otpauth:// URL for an authenticator-app QR.

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |

---

### `POST` /v1/auth/refresh

**Refresh**

#### Request Body (`application/json`)

Schema: `RefreshIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/auth/register

**Register**

#### Request Body (`application/json`)

Schema: `RegisterIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/auth/request-email-verification

**Request Email Verification**

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |

---

### `POST` /v1/auth/request-password-reset

**Request Password Reset**

Public: email a signed reset link. Always returns ok (never reveals whether the address
exists). No SMTP configured => the link is returned so an admin/dev can use it.

#### Request Body (`application/json`)

Schema: `PasswordResetRequestIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/auth/reset-password

**Reset Password**

Public: redeem a reset token, set a new password, and sign out all existing sessions.
Does NOT auto-login (user re-authenticates, re-prompting MFA).

#### Request Body (`application/json`)

Schema: `PasswordResetIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/auth/set-password

**Set My Password**

#### Request Body (`application/json`)

Schema: `PasswordIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/auth/verify-email

**Verify Email**

#### Request Body (`application/json`)

Schema: `TokenIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/oauth/callback

**Oauth Callback**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `code` | query | `object` | No |  |
| `state` | query | `object` | No |  |
| `error` | query | `object` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `text/html`: `string` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/auth-providers

**List Aps**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `AuthProviderOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/auth-providers

**Create Ap**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `AuthProviderCreate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `AuthProviderOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/projects/{project_id}/auth-providers/{ap_id}

**Delete Ap**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `ap_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/auth-providers/{ap_id}

**Get Ap**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `ap_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `AuthProviderOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/projects/{project_id}/auth-providers/{ap_id}

**Update Ap**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `ap_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `AuthProviderUpdate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `AuthProviderOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/projects/{project_id}/auth-providers/{ap_id}/connections/{end_user_id}

**Delete User Connection**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `ap_id` | path | `string` | Yes |  |
| `end_user_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/auth-providers/{ap_id}/connections/{end_user_id}

**Get User Connection**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `ap_id` | path | `string` | Yes |  |
| `end_user_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PUT` /v1/projects/{project_id}/auth-providers/{ap_id}/connections/{end_user_id}

**Set User Connection**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `ap_id` | path | `string` | Yes |  |
| `end_user_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `UserConnectionIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/auth-providers/{ap_id}/oauth/start

**Oauth Start**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `ap_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `object`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/auth-providers/{ap_id}/oauth/status

**Oauth Status**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `ap_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/auth-providers/{ap_id}/test

**Test Ap**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `ap_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `AuthTestIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---
