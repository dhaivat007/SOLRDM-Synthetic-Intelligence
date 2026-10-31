package org.solrdm.app;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.os.SystemClock;
import android.test.InstrumentationTestCase;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import java.io.File;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;

/** Two UI-driven phases separated by a process stop and same-key APK update. */
public class BridgeSmokeTest extends InstrumentationTestCase {
    private Activity activity;

    @Override protected void setUp() throws Exception {
        super.setUp();
        assertEquals("Tests must target the separately installed debug app",
                "org.solrdm.app.debug", context().getPackageName());
        assertEquals("The instrumentation APK must use the matching debug ID",
                "org.solrdm.app.debug.test", getInstrumentation().getContext().getPackageName());
    }

    private Context context() {
        return getInstrumentation().getTargetContext();
    }

    private File databaseFile() {
        return new File(context().getFilesDir(), "solrdm.sqlite3");
    }

    private void launch() throws Exception {
        Intent intent = new Intent(context(), MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        activity = getInstrumentation().startActivitySync(intent);
        getInstrumentation().waitForIdleSync();
        awaitResponse();
    }

    private JSONObject awaitResponse() throws Exception {
        long deadline = SystemClock.uptimeMillis() + 60000;
        final boolean[] done = new boolean[1];
        final String[] response = new String[1];
        while (SystemClock.uptimeMillis() < deadline) {
            getInstrumentation().runOnMainSync(() -> {
                Button status = activity.findViewById(R.id.status_button);
                TextView output = activity.findViewById(R.id.observation_output);
                assertNotNull(status);
                assertNotNull(output);
                done[0] = status.isEnabled();
                response[0] = output.getText().toString();
            });
            if (done[0]) return new JSONObject(response[0]);
            SystemClock.sleep(50);
        }
        fail("Python worker did not finish within 60 seconds; output=" + response[0]);
        return null;
    }

    private JSONObject click(int buttonId) throws Throwable {
        runTestOnUiThread(() -> {
            Button button = activity.findViewById(buttonId);
            assertNotNull(button);
            assertTrue("Command still busy", button.isEnabled());
            assertTrue("Command click was not handled", button.performClick());
        });
        return awaitResponse();
    }

    private void english(String text) throws Throwable {
        runTestOnUiThread(() -> {
            EditText field = activity.findViewById(R.id.observation_input);
            field.setText(text);
        });
    }

    private JSONObject observe(String subject, String relation, String object) throws Throwable {
        runTestOnUiThread(() -> {
            ((EditText) activity.findViewById(R.id.subject_input)).setText(subject);
            ((EditText) activity.findViewById(R.id.relation_input)).setText(relation);
            ((EditText) activity.findViewById(R.id.object_input)).setText(object);
        });
        return click(R.id.observe_button);
    }

    private int rowCount(String table) {
        SQLiteDatabase db = SQLiteDatabase.openDatabase(
                databaseFile().getAbsolutePath(), null, SQLiteDatabase.OPEN_READONLY);
        try {
            Cursor rows = db.rawQuery("SELECT COUNT(*) FROM " + table, null);
            try {
                assertTrue(rows.moveToFirst());
                return rows.getInt(0);
            } finally {
                rows.close();
            }
        } finally {
            db.close();
        }
    }

    private void assertFact(JSONArray facts, String subject, String relation,
                            String object, String source) throws Exception {
        for (int i = 0; i < facts.length(); i++) {
            JSONObject fact = facts.getJSONObject(i);
            if (subject.equals(fact.getString("subject"))
                    && relation.equals(fact.getString("relation"))
                    && object.equals(fact.getString("object"))
                    && (source == null || source.equals(fact.getString("source")))) return;
        }
        fail("Missing fact " + subject + "/" + relation + "/" + object + " in " + facts);
    }

    private void assertModuleStatus(JSONObject status, int observations) throws Exception {
        assertFalse(status.has("error"));
        assertEquals(observations, status.getInt("observations"));
        assertFalse(status.getBoolean("general_intelligence"));
        assertFalse(status.getBoolean("integration_complete"));
        JSONArray modules = status.getJSONArray("imported_modules");
        Set<String> actual = new HashSet<>();
        for (int i = 0; i < modules.length(); i++) actual.add(modules.getString(i));
        Set<String> expected = new HashSet<>(Arrays.asList(
                "solrdm", "solrdm.core", "solrdm.learning", "solrdm.neural",
                "solrdm.science", "solrdm.self_learning", "solrdm.english",
                "solrdm.internet", "solrdm.research", "solrdm.autonomy",
                "solrdm.language_learning", "solrdm.discovery_v05", "solrdm.agent_v06",
                "solrdm.compositional", "solrdm.benchmark", "solrdm.independent_eval"));
        assertEquals("Every supplied module must import on Android", expected, actual);
    }

    public void testFirstLaunchWritesObservation() throws Throwable {
        assertFalse("Start with cleared app data", databaseFile().exists());
        // Seed the earlier schema inside the new debug app; the separately
        // installed old app's private database remains untouched and isolated.
        SQLiteDatabase legacy = SQLiteDatabase.openOrCreateDatabase(databaseFile(), null);
        try {
            legacy.execSQL("CREATE TABLE observations(subject TEXT, predicate TEXT, "
                    + "object TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)");
            legacy.execSQL("INSERT INTO observations(subject,predicate,object) VALUES(?,?,?)",
                    new Object[]{"rotor", "part_of", "motor"});
        } finally {
            legacy.close();
        }
        launch();
        assertModuleStatus(click(R.id.status_button), 1);
        assertEquals(1, rowCount("observations"));
        assertEquals(1, rowCount("facts"));
        assertTrue(observe("The Motor", "Part Of", "A Machine").getBoolean("ok"));
        assertTrue(observe("wheel", "part_of", "car").getBoolean("ok"));
        assertEquals(3, rowCount("facts"));

        english("THE ROTOR");
        JSONArray facts = click(R.id.query_button).getJSONArray("facts");
        assertFact(facts, "rotor", "part_of", "motor", "android:legacy:observations:1");
        assertFact(facts, "rotor", "part_of", "machine", "inference");

        english("A Blade is part of the rotor");
        JSONObject parsed = click(R.id.interpret_button);
        assertEquals("candidate_fact", parsed.getString("intent"));
        assertFact(parsed.getJSONArray("candidate_facts"), "blade", "part_of", "rotor", null);
        assertEquals("Interpreting must not silently store candidate facts", 3, rowCount("facts"));

        JSONArray hypotheses = click(R.id.discover_button).getJSONArray("hypotheses");
        assertTrue(hypotheses.length() > 0);
        for (int i = 0; i < hypotheses.length(); i++) {
            assertEquals("unverified", hypotheses.getJSONObject(i).getString("status"));
        }
        assertEquals("Inferences must not become observations", 3, rowCount("facts"));
        assertTrue(observe("", "part_of", "machine").has("error"));
        assertEquals(3, rowCount("facts"));

        JSONObject trained = click(R.id.neural_button);
        long steps = trained.getJSONObject("training").getLong("steps");
        assertTrue("Neural updates must actually execute", steps > 0);
        JSONObject status = click(R.id.status_button);
        assertModuleStatus(status, 3);
        assertEquals(steps, status.getLong("neural_training_steps"));
        assertTrue(new File(databaseFile().getAbsolutePath() + ".neural.json").isFile());
        assertTrue(context().getSharedPreferences("smoke_expectations", Context.MODE_PRIVATE)
                .edit().putLong("neural_steps", steps).commit());
    }

    public void testRestartPreservesObservation() throws Throwable {
        // The shell has force-stopped and reinstalled the same signed APK.
        // Assert saved state before its Python runtime starts in the new process.
        assertTrue(databaseFile().isFile());
        assertEquals(3, rowCount("facts"));
        assertEquals(1, rowCount("observations"));
        long expectedSteps = context().getSharedPreferences("smoke_expectations", Context.MODE_PRIVATE)
                .getLong("neural_steps", -1);
        assertTrue(expectedSteps > 0);
        launch();
        JSONObject status = click(R.id.status_button);
        assertModuleStatus(status, 3);
        assertEquals("Neural state must survive process restart", expectedSteps,
                status.getLong("neural_training_steps"));
        assertEquals("Legacy migration must not duplicate observations", 3, rowCount("facts"));
        english("THE ROTOR");
        assertFact(click(R.id.query_button).getJSONArray("facts"),
                "rotor", "part_of", "machine", "inference");
        assertTrue(observe("wing", "part_of", "aircraft").getBoolean("ok"));
        assertEquals(4, rowCount("facts"));
        assertEquals(1, rowCount("observations"));
        assertModuleStatus(click(R.id.status_button), 4);
    }

    @Override protected void tearDown() throws Exception {
        try {
            if (activity != null) {
                getInstrumentation().runOnMainSync(() -> activity.finish());
                getInstrumentation().waitForIdleSync();
            }
        } finally {
            super.tearDown();
        }
    }
}
