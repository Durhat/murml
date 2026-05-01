/*
 * murml-Launcher
 *
 * Ein winziges Mach-O-Binary, das `run.sh` per posix_spawn startet, am Leben
 * bleibt und SIGINT/SIGTERM an den Subprocess weiterreicht.
 *
 * Hintergrund: macOS bindet TCC-Berechtigungen (Mikrofon, Eingabeüberwachung,
 * Bedienungshilfen) an das Mach-O-Binary, das die TCC-API aufruft, oder an das
 * "responsible parent" im Prozesstree. Wenn unser Bundle-Executable nur ein
 * Bash-Skript wäre, sähe macOS am Ende nur den Python-Subprocess und labelte
 * die Berechtigung als "python3.11". Mit einem signierten C-Launcher als
 * Eltern-Prozess bleibt das Bundle als responsible parent erkennbar.
 *
 * Bauen:
 *   cc -O2 -o murml launcher.c
 *
 * Im build_app.sh wird @@RUN_SH@@ durch den absoluten Pfad zu run.sh ersetzt.
 */

#include <errno.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

#define RUN_SCRIPT "@@RUN_SH@@"

static volatile pid_t g_child_pid = -1;

static void forward_signal(int sig) {
    if (g_child_pid > 0) {
        kill(g_child_pid, sig);
    }
}

int main(int argc, char *argv[]) {
    /* Argumente, die an run.sh übergeben werden (Subprocess sieht "run.sh"). */
    char *script_argv[] = { (char *)RUN_SCRIPT, NULL };

    pid_t child_pid;
    int rc = posix_spawn(&child_pid, RUN_SCRIPT,
                         NULL, NULL, script_argv, environ);
    if (rc != 0) {
        fprintf(stderr, "murml: posix_spawn failed: %s\n", strerror(rc));
        return 1;
    }
    g_child_pid = child_pid;

    /* Signale weiterreichen, damit der child sauber beendet werden kann. */
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = forward_signal;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGHUP,  &sa, NULL);

    int status = 0;
    while (waitpid(child_pid, &status, 0) == -1) {
        if (errno == EINTR) continue;
        perror("murml: waitpid");
        return 1;
    }

    if (WIFEXITED(status))   return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return 1;
}
