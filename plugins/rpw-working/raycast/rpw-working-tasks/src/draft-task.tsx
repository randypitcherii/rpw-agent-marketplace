import { Action, ActionPanel, Clipboard, Form, Icon, Toast, showToast } from "@raycast/api";

type DraftTaskFormValues = {
  title: string;
  context: string;
  priority: string;
  dueDate: Date | null;
};

function toIsoDate(value: Date | null): string {
  if (!value) {
    return "unspecified";
  }
  return value.toISOString().slice(0, 10);
}

function toTaskMarkdown(values: DraftTaskFormValues): string {
  const lines: string[] = [
    `- [ ] ${values.title.trim()}`,
    `  - priority: ${values.priority}`,
    `  - due: ${toIsoDate(values.dueDate)}`,
  ];

  const context = values.context.trim();
  if (context.length > 0) {
    lines.push(`  - context: ${context}`);
  }

  return lines.join("\n");
}

export default function Command() {
  async function handleSubmit(values: DraftTaskFormValues) {
    const trimmedTitle = values.title.trim();
    if (!trimmedTitle) {
      await showToast({
        style: Toast.Style.Failure,
        title: "Task title is required",
      });
      return;
    }

    const payload = toTaskMarkdown({ ...values, title: trimmedTitle });
    await Clipboard.copy(payload);
    await showToast({
      style: Toast.Style.Success,
      title: "Draft task copied",
      message: "Paste into your task system of record.",
    });
  }

  return (
    <Form
      navigationTitle="Draft RPW Task"
      actions={
        <ActionPanel>
          <Action.SubmitForm title="Copy Task Draft" onSubmit={handleSubmit} icon={Icon.Clipboard} />
        </ActionPanel>
      }
    >
      <Form.TextField id="title" title="Title" placeholder="Follow up on UCO stage progression gaps" />
      <Form.TextArea id="context" title="Context" placeholder="Customer/account, blockers, links, or next action notes." />
      <Form.Dropdown id="priority" title="Priority" defaultValue="medium">
        <Form.Dropdown.Item value="low" title="Low" />
        <Form.Dropdown.Item value="medium" title="Medium" />
        <Form.Dropdown.Item value="high" title="High" />
      </Form.Dropdown>
      <Form.DatePicker id="dueDate" title="Due Date" />
    </Form>
  );
}
