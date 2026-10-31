package org.solrdm.app;

import android.app.Activity;
import android.os.Bundle;
import android.text.InputFilter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import org.json.JSONObject;

/** Offline controls for the supplied research engine; Python work stays off the UI thread. */
public class MainActivity extends Activity {
    private static final ExecutorService ENGINE_WORKER = Executors.newSingleThreadExecutor();
    private final List<Button> commands = new ArrayList<>();
    private TextView output;
    private EditText subject;
    private EditText relation;
    private EditText object;
    private EditText english;
    private Future<?> pending;
    private String dbPath;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        // Reuse the original observation prototype's path so its SQLite data can migrate.
        dbPath = new File(getFilesDir(), "solrdm.sqlite3").getAbsolutePath();
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int padding = Math.round(16 * getResources().getDisplayMetrics().density);
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setPadding(padding, padding, padding, padding);
        scroll.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(padding + insets.getSystemWindowInsetLeft(),
                    padding + insets.getSystemWindowInsetTop(),
                    padding + insets.getSystemWindowInsetRight(),
                    padding + insets.getSystemWindowInsetBottom());
            return insets;
        });
        scroll.addView(layout);
        TextView heading = new TextView(this);
        heading.setText(R.string.app_heading);
        heading.setTextSize(22);
        layout.addView(heading);
        TextView limitations = new TextView(this);
        limitations.setText(R.string.engine_limits);
        layout.addView(limitations);
        subject = input(layout, R.id.subject_input, R.string.subject_hint, 200, true);
        relation = input(layout, R.id.relation_input, R.string.relation_hint, 200, true);
        object = input(layout, R.id.object_input, R.string.object_hint, 200, true);
        Button observe = button(layout, R.id.observe_button, R.string.save_observation);
        observe.setOnClickListener(view -> {
            try {
                JSONObject fact = new JSONObject();
                fact.put("subject", subject.getText().toString());
                fact.put("relation", relation.getText().toString());
                fact.put("object", object.getText().toString());
                call("observe", fact.toString());
            } catch (Exception error) {
                output.setText(getString(R.string.engine_error, error.getMessage()));
            }
        });
        english = input(layout, R.id.observation_input, R.string.english_hint, 2000, false);
        button(layout, R.id.interpret_button, R.string.interpret_english)
                .setOnClickListener(view -> call("interpret", english.getText().toString()));
        button(layout, R.id.query_button, R.string.query_memory)
                .setOnClickListener(view -> call("query", english.getText().toString()));
        button(layout, R.id.discover_button, R.string.discover_hypotheses)
                .setOnClickListener(view -> call("discover", ""));
        button(layout, R.id.neural_button, R.string.train_neural)
                .setOnClickListener(view -> call("neural_train", ""));
        button(layout, R.id.status_button, R.string.engine_status)
                .setOnClickListener(view -> call("status", ""));
        output = new TextView(this);
        output.setId(R.id.observation_output);
        output.setTextIsSelectable(true);
        layout.addView(output);
        setContentView(scroll);
        call("status", "");
    }

    private EditText input(LinearLayout layout, int id, int hint, int maxLength,
                           boolean singleLine) {
        EditText field = new EditText(this);
        field.setId(id);
        field.setHint(hint);
        field.setSingleLine(singleLine);
        field.setFilters(new InputFilter[]{new InputFilter.LengthFilter(maxLength)});
        layout.addView(field);
        return field;
    }

    private Button button(LinearLayout layout, int id, int text) {
        Button button = new Button(this);
        button.setId(id);
        button.setText(text);
        commands.add(button);
        layout.addView(button);
        return button;
    }

    private void call(String command, String payload) {
        for (Button button : commands) button.setEnabled(false);
        output.setText(R.string.engine_working);
        final android.content.Context appContext = getApplicationContext();
        final String path = dbPath;
        pending = ENGINE_WORKER.submit(() -> {
            String result;
            try {
                if (!Python.isStarted()) Python.start(new AndroidPlatform(appContext));
                String raw = Python.getInstance().getModule("android_bridge")
                        .callAttr("execute", path, command, payload).toString();
                result = new JSONObject(raw).toString(2);
            } catch (Exception error) {
                result = getString(R.string.engine_error, error.getMessage());
            }
            final String response = result;
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) return;
                output.setText(response);
                for (Button button : commands) button.setEnabled(true);
            });
        });
    }

    @Override protected void onDestroy() {
        // Cancel work which has not started; an active transaction may finish safely.
        if (pending != null) pending.cancel(false);
        super.onDestroy();
    }
}
