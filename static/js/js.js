var process_response = function(result) {
    $('#ajax_messages').html(result['messages']);
}

var update_counter = function(div,what,object_type,object_id) {
    var url = '/ajax/count/';
    $.ajax({
          url: url,
          type : "POST",
          dataType : 'json',
          data : {   what: what,
                        object_type: object_type,
                        object_id : object_id },
          success : function(result){
            $(div).html(result['counter']);
            $(div).animate({opacity:0},200,"linear",function(){
              $(this).animate({opacity:1},200);
            });
          },
          error: function(xhr,resp,text) {
            console.log('Error getting counter');
            console.log(resp);
            console.log(text);
            console.log(xhr);
          }
      });
}

var process_error_response = function(xhr,resp,text) {
    console.log('Error in ajax call!');
    console.log(resp);
    console.log(text);
    console.log(xhr);
    var html = '<div class="alert alert-danger alert-dismissible fade show" role="alert">'
             + '<button type="button" class="close" data-dismiss="alert" aria-label="close">&#215;</button>'
             + '<b>Error</b>: '
             + $("<div>").text(xhr.responseText).html();
             + '</div>'
    $('#ajax_messages').html(html);
    $("html, body").animate({ scrollTop: 0 }, "slow");
}

var link_external_website = function(url) {
    $('#url_container').html($('#url_container').html().replace('XXXX',url));
    $('#different_website_modal').modal('show');
    $('#different_website_modal_button').on('click',function(){
        window.open(url);
        $('#different_website_modal').modal('hide');
    });
}

//
var add_tag = function (url_tag_add,tag_name, object_type, object_id) {
    $.ajax({
          url: url_tag_add,
          type : "POST",
          dataType : 'json',
          data : {   tag_name: tag_name,
                        object_type: object_type,
                        object_id : object_id },
          success : process_response,
          error: process_error_response
      });
    console.log('Tag ' + tag_name + ' added to ' + object_type + ' ' + object_id);
}


var prepare_tags = function (url_tag_add,url_tag_list,url_tag_remove,object_type,object_id,pre_populated_tags) {
    $(document).ready(function () {
      $("#tags-input").tokenInput(url_tag_list, {
          method: 'POST',
          preventDuplicates : true,
          noResultsText: "No results found. To create a new tag, click here",
          // theme: 'mac',
          onAdd: function (item) {
              add_tag(url_tag_add,item.name,object_type,object_id);
          },
          onDelete: function (item) {
              $.ajax({
                    url: url_tag_remove,
                    type : "POST",
                    dataType : 'json',
                    data : {   tag_name: item.name,
                                  object_type: object_type,
                                  object_id : object_id },
                    success : process_response,
                    error: process_error_response
                });
              console.log('Tag ' + item.name + ' deleted from ' + object_type + ' ' + object_id);
          },
          onResult: function (results) {
              if(results.length == 0) {
                  var h = 'To create a new tag <button type="button" class="btn btn-outline-success btn-small" data-toggle="modal" data-target="#create_tag_modal">click here</button>';
                  $('#create_tag_message').html(h);
              }
              return results;
          },
          prePopulate:  pre_populated_tags
      });
    });
};

// HOOKS 'Create tag' BUTTON
$(document).ready(function(){
    $("#create_tag_button").on('click', function(){
      var tag_name = $('#tag-name').val();
      $("#tags-input").tokenInput("add", {id: 999, name: tag_name});
      $('#create_tag_modal').modal('hide');
    });
});

// HOOKS 'Clear selection' BUTTON
$(document).ready(function(){
    $("#clear_selection_button").on('click', function(){
      $.ajax({
          url: '/ajax/selection/clear',
          type : "POST",
          dataType : 'json',
          data : [],
          success : process_response,
          error: process_error_response
      });
      $('#clear_selection_modal').modal('hide')
    });
});

var table_functions = function(searching=true,paging=true,pageLength=250) {

    $(document).ready(function(){
        // toggle all checkboxes
        $('#select_all_checkboxes').click(function(e){
          var table= $(e.target).closest('table');
          $('td input:checkbox',table).prop('checked',this.checked);
        });
        // click on button submit for users
        $("[name='add_selected_users']").on('click', function(){
          // send ajax
          $.ajax({
              url: '/ajax/selection/',               // {% url 'add_to_selection' %}
              type : "POST",
              dataType : 'json',
              data : $("#users_form").serialize(),
              success : process_response,
              error: process_error_response
          })
        });
        // click on button submit for tweets
        $("[name='add_selected_tweets']").on('click', function(){
          // send ajax
          $.ajax({
              url: '/ajax/selection/',               // {% url 'add_to_selection' %}
              type : "POST",
              dataType : 'json',
              data : $("#tweets_form").serialize(),
              success : process_response,
              error: process_error_response
          })
        });
    });

    $(document).ready(function () {
        if($('#twitter_users_table').length != 0) {
            $('#twitter_users_table').DataTable({
            "searching": searching,
             "paging":paging,
             "pageLength":pageLength,
             "lengthMenu": [ 25, 50, 100, 250, 500, 1000 ]
            });
            $('.dataTables_length').addClass('bs-select');
        }

       if($('#tweets_table').length != 0) {
           $('#tweets_table').DataTable({
            "searching": searching,
             "paging":paging,
             "pageLength":pageLength,
             "lengthMenu": [ 25, 50, 100, 250, 500, 1000 ]
            });
            $('.dataTables_length').addClass('bs-select');
       }
    });
}