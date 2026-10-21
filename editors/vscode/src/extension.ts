import * as cp from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';
import {
  Executable,
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
  TransportKind,
} from 'vscode-languageclient/node';

type ServerMode = 'lsp' | 'dap';

interface ServerCommand {
  command: string;
  args: string[];
  cwd?: string;
}

let client: LanguageClient | undefined;
let output: vscode.OutputChannel;
let restarting = false;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  output = vscode.window.createOutputChannel('Vanta');
  context.subscriptions.push(output);
  context.subscriptions.push(
    vscode.commands.registerCommand('vanta.restartServer', () =>
      restart(context)),
  );
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration('vanta.server.path')) {
        void restart(context);
      }
    }),
  );

  const debugConfigurationProvider =
    vscode.debug.registerDebugConfigurationProvider('vanta', {
      resolveDebugConfiguration(folder, config) {
        if (!config.program) {
          const editor = vscode.window.activeTextEditor;
          if (editor?.document.languageId === 'vanta') {
            config.program = editor.document.uri.fsPath;
          }
        }
        if (!config.cwd && folder) {
          config.cwd = folder.uri.fsPath;
        }
        return config;
      },
    });
  context.subscriptions.push(debugConfigurationProvider);

  const debugAdapterFactory =
    vscode.debug.registerDebugAdapterDescriptorFactory('vanta', {
      createDebugAdapterDescriptor(session) {
        const workspace = session.workspaceFolder?.uri.fsPath ??
          vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        const server = resolveServer('dap', workspace);
        if (server === undefined) {
          throw new Error(
            'Vanta: could not find the vanta executable or Python package ' +
            'for the debugger.');
        }
        const env = debugAdapterEnv(workspace);
        output.appendLine(
          `Starting Vanta debug adapter: ${server.command} ` +
          server.args.join(' '));
        return new vscode.DebugAdapterExecutable(
          server.command, server.args, { cwd: server.cwd, env });
      },
    });
  context.subscriptions.push(debugAdapterFactory);
  await start(context);
}

function debugAdapterEnv(workspace?: string): { [key: string]: string } {
  const env: { [key: string]: string } = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined) {
      env[key] = value;
    }
  }
  const configured =
    (vscode.workspace.getConfiguration('vanta').get<string>('debug.gdbPath') ?? '')
      .trim();
  if (configured) {
    let expanded = expandConfiguredPath(configured, workspace);
    if (workspace !== undefined && !path.isAbsolute(expanded) &&
        looksLikePath(expanded)) {
      expanded = path.resolve(workspace, expanded);
    }
    env.VANTA_GDB = expanded;
  }
  return env;
}

export async function deactivate(): Promise<void> {
  await stop();
}

async function start(context: vscode.ExtensionContext): Promise<void> {
  const server = resolveServer('lsp');
  if (server === undefined) {
    const action = await vscode.window.showErrorMessage(
      'Vanta: could not find the vanta executable or a Python environment ' +
      'with the vanta package installed.',
      'Open Settings',
      'Installation Guide',
    );
    if (action === 'Open Settings') {
      await vscode.commands.executeCommand(
        'workbench.action.openSettings', 'vanta.server.path');
    } else if (action === 'Installation Guide') {
      await vscode.env.openExternal(
        vscode.Uri.parse('https://pypi.org/project/vanta-lang/'));
    }
    return;
  }

  output.appendLine(`Starting Vanta language server: ${server.command} ` +
    server.args.join(' '));
  const executable: Executable = {
    command: server.command,
    args: server.args,
    transport: TransportKind.stdio,
    options: {
      cwd: server.cwd,
      env: process.env,
    },
  };
  const serverOptions: ServerOptions = executable;
  const clientOptions: LanguageClientOptions = {
    documentSelector: [
      { scheme: 'file', language: 'vanta' },
      { scheme: 'untitled', language: 'vanta' },
    ],
    synchronize: {
      configurationSection: 'vanta',
    },
    outputChannel: output,
  };
  client = new LanguageClient(
    'vanta', 'Vanta Language Server', serverOptions, clientOptions);
  context.subscriptions.push(client);
  try {
    await client.start();
    output.appendLine('Vanta language server is ready.');
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`Failed to start: ${message}`);
    void vscode.window.showErrorMessage(
      `Vanta: language server failed to start: ${message}`);
    await stop();
  }
}

async function restart(context: vscode.ExtensionContext): Promise<void> {
  if (restarting) {
    return;
  }
  restarting = true;
  try {
    await stop();
    await start(context);
  } finally {
    restarting = false;
  }
}

async function stop(): Promise<void> {
  if (client === undefined) {
    return;
  }
  const current = client;
  client = undefined;
  try {
    await current.stop();
  } catch {
    // The server may already have exited because the configuration was
    // invalid. Restarting should still be possible.
  }
  current.dispose();
}

function resolveServer(
  mode: ServerMode,
  requestedWorkspace?: string,
): ServerCommand | undefined {
  const workspace = requestedWorkspace ??
    vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  const config = vscode.workspace.getConfiguration('vanta');
  const configured = (config.get<string>('server.path') ?? '').trim();
  if (configured) {
    let expanded = expandConfiguredPath(configured, workspace);
    if (looksLikePath(expanded)) {
      if (workspace !== undefined && !path.isAbsolute(expanded)) {
        expanded = path.resolve(workspace, expanded);
      }
      if (!isFile(expanded)) {
        output.appendLine(
          `Configured vanta.server.path not found: ${expanded}`);
        return undefined;
      }
    }
    return {
      command: expanded,
      args: serverArguments(expanded, mode),
      cwd: workspace,
    };
  }

  const executable = findVantaExecutable(workspace);
  if (executable !== undefined) {
    return { command: executable, args: [mode], cwd: workspace };
  }

  const python = findPython(workspace);
  if (python !== undefined) {
    output.appendLine(`Using Python module fallback: ${python}`);
    return {
      command: python,
      args: ['-m', 'compiler', mode],
      cwd: workspace,
    };
  }
  return undefined;
}

function expandConfiguredPath(value: string, workspace?: string): string {
  let expanded = value;
  if (expanded === '~') {
    expanded = os.homedir();
  } else if (expanded.startsWith('~/') || expanded.startsWith('~\\')) {
    expanded = path.join(os.homedir(), expanded.slice(2));
  }
  if (workspace !== undefined && expanded.includes('${workspaceFolder}')) {
    expanded = expanded.replace(/\$\{workspaceFolder\}/g, workspace);
  }
  return expanded;
}

function isFile(value: string): boolean {
  try {
    return fs.statSync(value).isFile();
  } catch {
    return false;
  }
}

function looksLikePath(value: string): boolean {
  return value.includes('/') || value.includes('\\') || /^[A-Za-z]:/.test(value);
}

function serverArguments(command: string, mode: ServerMode): string[] {
  const base = path.basename(command).toLowerCase().replace(/\.exe$/, '');
  if (/^(?:python(?:3(?:\.\d+)?m?)?|py|pypy3?)$/.test(base)) {
    return ['-m', 'compiler', mode];
  }
  return [mode];
}

function findVantaExecutable(workspace?: string): string | undefined {
  if (workspace !== undefined) {
    for (const venv of ['.venv', 'venv', 'env']) {
      for (const relative of executableNames()) {
        const candidate = path.join(workspace, venv, relative);
        if (isFile(candidate)) {
          return candidate;
        }
      }
    }
  }
  return findOnPath('vanta');
}

function findPython(workspace?: string): string | undefined {
  const candidates: string[] = [];
  if (workspace !== undefined) {
    for (const venv of ['.venv', 'venv', 'env']) {
      const base = path.join(workspace, venv);
      if (process.platform === 'win32') {
        candidates.push(path.join(base, 'Scripts', 'python.exe'));
      } else {
        candidates.push(path.join(base, 'bin', 'python3'));
        candidates.push(path.join(base, 'bin', 'python'));
      }
    }
  }
  const pythonNames = process.platform === 'win32'
    ? ['python3', 'python', 'py']
    : ['python3', 'python'];
  for (const name of pythonNames) {
    const found = findOnPath(name);
    if (found !== undefined) {
      candidates.push(found);
    }
  }
  for (const candidate of candidates) {
    if (!isFile(candidate)) {
      continue;
    }
    try {
      cp.execFileSync(candidate, ['-c', 'import compiler'], {
        cwd: workspace,
        timeout: 3000,
        stdio: 'ignore',
        windowsHide: true,
      });
      return candidate;
    } catch {
      // Try the next interpreter. This is expected when Python is present
      // but vanta-lang was installed into a different environment.
    }
  }
  return undefined;
}

function executableNames(): string[] {
  if (process.platform === 'win32') {
    return [
      path.join('Scripts', 'vanta.exe'),
      path.join('Scripts', 'vanta.cmd'),
      path.join('Scripts', 'vanta.bat'),
    ];
  }
  return [path.join('bin', 'vanta')];
}

function findOnPath(name: string): string | undefined {
  const pathValue = process.env.PATH ?? '';
  const extensions = process.platform === 'win32'
    ? (process.env.PATHEXT ?? '.COM;.EXE;.BAT;.CMD').split(';')
    : [''];
  for (const directory of pathValue.split(path.delimiter)) {
    if (!directory) {
      continue;
    }
    for (const extension of extensions) {
      const candidate = path.join(directory, name + extension);
      if (isFile(candidate)) {
        return candidate;
      }
    }
  }
  return undefined;
}
